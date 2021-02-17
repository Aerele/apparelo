# Copyright (c) 2013, Aerele Technologies Private Limited and contributors
# For license information, please see license.txt

from __future__ import unicode_literals
import frappe
from frappe import _
from apparelo.apparelo.doctype.dc.dc import get_receivable_list_values
from frappe.utils import flt
from erpnext.stock.doctype.item.item import get_uom_conv_factor
from apparelo.apparelo.utils.item_utils import get_item_attribute_set
from operator import itemgetter

def execute(filters=None):
	columns, data = [], []
	if filters:
		columns, size_list = get_columns(filters, columns)
		data = get_data(filters, data, size_list)
	return columns, data

def get_columns(filters, columns):
	size_list = []
	columns += [
			_('Part') + ":Data:100",
			_('Colour') + ":Data:100"
		]
	ipd = frappe.db.get_value('Lot Creation',filters['lot'], 'item_production_detail')
	ipd_doc = frappe.get_doc('Item Production Detail', ipd)
	for row in ipd_doc.size:
		columns += [
			_(row.size) + ":Data:100"
		]
		size_list.append(row.size)
	return columns, size_list

def get_data(filters, data, size_list):
	if 'show_planned_qty' in filters and filters['show_planned_qty']:
		data = show_planned_qty(filters, len(size_list))

	return data


def show_planned_qty(filters, size_len):
	lot = filters['lot']
	lot_ipd = frappe.db.get_value(
		'Lot Creation', {'name': lot}, 'item_production_detail')

	ipd_bom_mapping = frappe.db.get_value(
		'IPD BOM Mapping', {'item_production_details': lot_ipd})
	ipd_item_mapping = frappe.get_doc(
		"IPD Item Mapping", {'item_production_details': lot_ipd})
	boms = frappe.get_doc(
		'IPD BOM Mapping', ipd_bom_mapping).get_process_boms('Cutting')
	data = frappe.get_list('BOM', filters={'name': ['in', boms]},
					group_by='item', fields=['item', 'name as bom'])

	receivable_list = {}
	item_mapping_validator = [x["item"] for x in frappe.get_list(
		"Item Mapping", {"parent": ipd_item_mapping.name, "process_1": 'Cutting'}, "item")]
	data_with_removed_invalids_list = []
	for item in data:
		if item['item'] in item_mapping_validator:
			receivable_list[item['item']] = 0
			data_with_removed_invalids_list.append(
				item)

	data = data_with_removed_invalids_list

	lot_items = frappe.get_list('Lot Creation Plan Item', filters={
								'parent': lot}, fields=['item_code', 'planned_qty', 'bom_no', 'stock_uom'])
	
	receivable_list = get_receivable_list_values(lot_items, receivable_list)

	percentage_in_excess = frappe.db.get_value(
		'Lot Creation', lot, 'percentage')
	if percentage_in_excess:
		percentage_in_excess = (flt(percentage_in_excess) / 100)

	for d in data:
		item = d['item']
		stock_uom = frappe.db.get_value('Item', item, 'stock_uom')
		if frappe.db.get_value('UOM', stock_uom, 'must_be_whole_number'):
			receivable_list[item] = int(receivable_list[item] + (receivable_list[item] * percentage_in_excess))
		else:
			receivable_list[item] = receivable_list[item] + (receivable_list[item] * percentage_in_excess)

	new_data = []
	for d in data:
		item = frappe.get_doc('Item', d['item'])
		attribute_set = get_item_attribute_set(list(map(lambda x: x.attributes,[item])))
		d['qty'] = receivable_list[d['item']]
		if frappe.db.get_value('UOM', item.stock_uom, 'must_be_whole_number'):
			d['qty'] = int(d['qty'])
		
		new_data.append({
			'colour': attribute_set['Apparelo Colour'][0],
			'part': attribute_set['Part'][0],
			attribute_set['Apparelo Size'][0].lower().replace(' ','_'): d['qty']
		})

	new_data = sorted(new_data, key=itemgetter('part', 'colour'))
	combined_data = []
	for out_idx in range(0,len(new_data), size_len):
		combined_dict = new_data[out_idx]
		for in_idx in range(out_idx+1, out_idx+size_len):
			combined_dict.update(new_data[in_idx])
		combined_data.append(combined_dict)

	return combined_data