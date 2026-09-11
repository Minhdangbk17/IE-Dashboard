"""Shared SQLite schema constants for Dyeing features.

The application currently uses sqlite3 directly rather than SQLAlchemy. Keeping
these field contracts in one module avoids duplicating the Batch Detail mapping
between the importer, manual entry and reporting engines.
"""
from __future__ import annotations

AVAILABILITY_TABLE = "availability_logs"
BATCH_DETAILS_TABLE = "batch_details"

AVAILABILITY_MANUAL_FIELDS = (
    "batch", "batch_ref_no", "fabric_type", "brand_name", "machine", "capacity_kg",
    "program", "start_time", "end_time", "production_date", "planned_prd_time_hour",
    "running_time_hour", "total_downtime_hour", "rework_hour", "adjust_color_hour", "bleaching_hour", "load_hour",
    "unload_hour", "sample_checking_hour", "ph_checking_hour", "wait_chemical_load_hour", "wait_color_load_hour",
    "wait_fabric_hour", "wait_water_hour", "wait_steam_hour", "cleaning_hour", "maintenance_hour", "no_order_hour",
    "others_hour", "entry_type",
)

BATCH_DETAIL_FIELDS = (
    "dyelot", "customer", "color", "order_no", "greige_code", "recipe_no", "colour_no", "shade",
    "customer_color", "is_rework", "machine", "machine_group",
    "fabric_code", "fabric_type", "fabric_content", "wo_qty", "batch_type", "batch_state", "formula_code",
    "formula_type", "process_type", "weight", "redye", "liquor_ratio", "liquor_quantity",
    "weight_per_area", "greige_width", "reel_speed", "pump_speed", "max_reel_speed", "absorption", "nozzle",
    "sap_lot", "customer_code", "customer_po", "soft_water",
    "hot_water", "hard_water", "mix_water", "sum_water", "water_per_kg", "power", "power_per_kg", "heating_energy",
    "steam_per_kg", "dye_cost", "chemical_cost", "correction_cnt", "alarm_cnt", "intervention_cnt", "total_correction_cnt",
    "washing_correction", "dyestuff_correction", "chemical_correction",
    "schedule_time", "start_time", "end_time", "run_time", "set_time", "stop_time", "operator_time",
    "correction_time", "manual_time", "stop_alarm_time", "hold_alarm_time", "diff_time", "percent",
    "fuyang_request", "note1", "note2", "note3", "note4", "note5",
)
