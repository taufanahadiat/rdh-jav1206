#!/usr/bin/env python3
import argparse
import json
import sys

import snap7
from snap7.util import get_bool, get_real


PLC_IP = "169.254.254.45"
RACK = 0
SLOT = 1

PRODUCT = "PCL-25"
DENSITY_G_CM3 = 0.91


def read_real(plc: snap7.client.Client, db_num: int, offset: int) -> float:
    data = bytearray(plc.db_read(db_num, offset, 4))
    return float(get_real(data, 0))


def read_bool(
    plc: snap7.client.Client, db_num: int, byte_offset: int, bit_offset: int
) -> bool:
    data = bytearray(plc.db_read(db_num, byte_offset, 1))
    return bool(get_bool(data, 0, bit_offset))


def build_payload(plc: snap7.client.Client) -> dict:
    line_speed_m_min = read_real(plc, 325, 1498)
    avg_thickness_um = read_real(plc, 326, 2716)
    web_width = read_real(plc, 326, 2720)
    meter_set = read_real(plc, 330, 3006)
    meter_counter = read_real(plc, 330, 3010)
    min_remaining = read_real(plc, 330, 3018)
    treatment_inside_corona = read_bool(plc, 326, 3666, 2)
    treatment_outside_corona = read_bool(plc, 326, 3822, 2)

    # Convert units to SI before calculating volume/mass:
    # thickness: um -> m, width: mm -> m, density: g/cm^3 -> kg/m^3
    thickness_m = avg_thickness_um * 1e-6
    width_m = web_width * 1e-3
    volume_m3 = thickness_m * width_m * meter_counter
    density_kg_m3 = DENSITY_G_CM3 * 1000.0
    mass_kg = volume_m3 * density_kg_m3

    # Line speed is m/min, so production time for current meter counter:
    # hours = meter_counter(m) / (line_speed(m/min) * 60(min/h))
    line_speed_m_h = line_speed_m_min * 60.0
    estimated_hours = 0.0
    output_on_winder = 0.0
    if line_speed_m_h > 0 and meter_counter > 0:
        estimated_hours = meter_counter / line_speed_m_h
        if estimated_hours > 0:
            output_on_winder = mass_kg / estimated_hours

    return {
        "product": PRODUCT,
        "density_g_cm3": DENSITY_G_CM3,
        "density_kg_m3": density_kg_m3,
        "avg_thickness_um": avg_thickness_um,
        "line_speed_m_min": line_speed_m_min,
        "line_speed_m_h": line_speed_m_h,
        "volume_m3": volume_m3,
        "mass_kg": mass_kg,
        "estimated_hours": estimated_hours,
        "meter_set_m": meter_set,
        "meter_counter_m": meter_counter,
        "min_remaining": min_remaining,
        "output_on_winder_kg_h": output_on_winder,
        "treatment_inside_corona": treatment_inside_corona,
        "treatment_outside_corona": treatment_outside_corona,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true", help="Output JSON only")
    args = parser.parse_args()

    plc = snap7.client.Client()
    try:
        plc.connect(PLC_IP, RACK, SLOT)
        if not plc.get_connected():
            raise RuntimeError("Failed to connect to PLC")

        payload = build_payload(plc)
        if args.json:
            print(json.dumps(payload, ensure_ascii=False))
        else:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        err = {"error": str(exc)}
        print(json.dumps(err, ensure_ascii=False))
        return 1
    finally:
        try:
            if plc.get_connected():
                plc.disconnect()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
