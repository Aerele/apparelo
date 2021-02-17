// Copyright (c) 2016, Aerele Technologies Private Limited and contributors
// For license information, please see license.txt
/* eslint-disable */

frappe.query_reports["Cutting Report"] = {
	"filters": [
		{
			"fieldname":"lot",
			"label": __("Lot"),
			"fieldtype": "Link",
			"options": "Lot Creation",
			"reqd": 1
		},
		{
			"fieldname":"show_planned_qty",
			"label": __("Show Planned Qty"),
			"fieldtype": "Check",
			"Default": 0,
		}

	]
};