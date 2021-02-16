# Copyright (c) 2013, Aerele Technologies Private Limited and contributors
# For license information, please see license.txt

from __future__ import unicode_literals
import frappe
from frappe import _

def execute(filters=None):
	columns, data = [], []
	if filters:
		columns = get_columns(filters, columns)
	return columns, data

def get_columns(filters, columns):
	ipd = frappe.db.get_value('Lot Creation',filters['lot'], 'item_production_detail')
	ipd_doc = frappe.get_doc('Item Production Detail', ipd)
	for row in ipd_doc.size:
		columns += [
			_(row.size) + ":Data:100"
		]
	return columns

