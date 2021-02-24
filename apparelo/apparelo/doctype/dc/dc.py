# -*- coding: utf-8 -*-
# Copyright (c) 2019, Aerele Technologies Private Limited and contributors
# For license information, please see license.txt

from __future__ import unicode_literals
import frappe
import json
import math
from frappe import _, msgprint
from frappe.model.mapper import get_mapped_doc
from six import string_types, iteritems
from frappe.model.document import Document
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.utils import cstr, flt, cint, nowdate, add_days, comma_and, now_datetime, ceil
from erpnext.stock.report.stock_balance.stock_balance import execute
from erpnext.buying.doctype.purchase_order.purchase_order import make_rm_stock_entry
from erpnext import get_default_company
from erpnext.manufacturing.doctype.production_plan.production_plan import get_items_for_material_requests
from erpnext.stock.doctype.item.item import get_uom_conv_factor
from apparelo.apparelo.utils.utils import generate_printable_list, generate_html_from_list, generate_total_row_and_column, generate_empty_column_list
from apparelo.apparelo.utils.item_utils import get_item_attribute_set


class DC(Document):
	def validate(self):
		self.validate_delivery()
		self.items = list(filter(lambda x: x.quantity != 0, self.items))
		self.return_materials = list(filter(lambda x: x.qty != 0, self.return_materials))

		if not self.items:
			frappe.throw(_(f'Please enter delivery quantity for delivery items'))
		if not self.return_materials:
			frappe.throw(_(f'Please enter expected quantity for return materials'))
		# printable table creation
		items = [item for item in self.items if vars(item)['deliver_later']==0]
		printable_list_d = generate_printable_list(items, get_grouping_params(self.process_1), self.lot, field='quantity')
		generate_total_row_and_column(printable_list_d)
		printable_list_d[0]['section_title'] = 'Delivery Items'
		deliver_later_items = [item for item in self.items if vars(item)['deliver_later']!=0]
		location_wise_items={}
		printable_list_l=[]
		if deliver_later_items:
			for items in deliver_later_items:
				if not vars(items)['delivery_location'] in location_wise_items:
					location_wise_items[vars(items)['delivery_location']]=[items]
				else:
					location_wise_items[vars(items)['delivery_location']].append(items)
			for location in location_wise_items.keys():
				printable_list = generate_printable_list(location_wise_items[location], get_grouping_params(self.process_1), self.lot, field='quantity')
				generate_total_row_and_column(printable_list)
				generate_empty_column_list(printable_list)
				printable_list[0]['section_title'] = location
				printable_list_l+=printable_list
		printable_list_r = generate_printable_list(self.return_materials, get_grouping_params(self.process_1), self.lot, field='qty')
		generate_total_row_and_column(printable_list_r)
		printable_list_r[0]['section_title'] = 'Expected Return Items'
		self.dc_cloth_quantity = generate_html_from_list(printable_list_d+printable_list_l+printable_list_r)

	def on_submit(self):
		new_po = self.create_purchase_order()
		stock_dict = get_stock_dict(new_po)
		stock_entry = frappe.get_doc(stock_dict)
		stock_entry.dc = self.name
		stock_entry.save()
		stock_entry.submit()

		msgprint(_("{0} created").format(comma_and(
			"""<a href="#Form/Purchase Order/{0}">{1}</a>""".format(new_po.name, new_po.name))))
		msgprint(_("{0} created").format(comma_and(
			"""<a href="#Form/Stock Entry/{0}">{1}</a>""".format(stock_entry.name, stock_entry.name))))

	def on_cancel(self):
		self.db_set("docstatus",2)
		msgprint(_("{0} cancelled").format(comma_and("""<a href="#Form/DC/{0}">{1}</a>""".format(self.name, self.name))))
		
	def create_purchase_order(self):
		dc_items = []
		lot_warehouse = frappe.db.get_value("Warehouse", {
											'location': self.location, 'lot': self.lot, 'warehouse_type': "Actual"}, 'name')
		if not self.expect_return_items_at:
			self.expect_return_items_at = self.location
		expect_return_items_at = frappe.db.get_value("Warehouse", {
											'location': self.expect_return_items_at, 'lot': self.lot, 'warehouse_type': "Actual"}, 'name')
		supplier_warehouse = frappe.db.get_value(
			"Warehouse", {'supplier': self.supplier}, 'name')
		for item_ in self.return_materials:
			dc_items.append(
				{"item_code": item_.item_code,
				 "schedule_date": add_days(nowdate(), 7),
				 "qty": item_.qty,
				 "bom": item_.bom,
				 "rate": 1
				 })
		po = frappe.get_doc({
			"doctype": "Purchase Order",
			"supplier": self.supplier,
			"dc": self.name,
			"lot": self.lot,
			"schedule_date": add_days(nowdate(), 7),
			"set_warehouse": expect_return_items_at,
			"set_reserve_warehouse": lot_warehouse,
			"is_subcontracted": "Yes",
			"supplier_warehouse": supplier_warehouse,
			"items": dc_items})
		po.save()
		# set_reserve_warehouse related code does not exist in python hence the following is required
		supplied_items_reserve_warehouse = self.get_supplied_items_reserve_warehouse()
		for item in po.supplied_items:
			if item.rm_item_code in supplied_items_reserve_warehouse:
				item.reserve_warehouse = supplied_items_reserve_warehouse[item.rm_item_code]
			else:
				item.reserve_warehouse = lot_warehouse
		po.save()
		stock_dict = get_stock_dict(po)
		supplied_items = {}
		for item in stock_dict['items']:
			if not item['item_name'] in supplied_items:
				supplied_items[item['item_name']] = item['transfer_qty']
			else:
				supplied_items[item['item_name']] += item['transfer_qty']
		qty_wise_dc_item = self.get_dc_item()
		for dc_item in qty_wise_dc_item:
			item_name = dc_item['item']
			idx = dc_item['idx']
			qty = dc_item['qty']
			if not item_name in supplied_items:
				frappe.throw(_(f'Item {item_name} entered in delivery items at row {idx} was not found in purchase order supplied items'))
			else:
				transfer_qty = round(supplied_items[item_name],3)
				if not round((transfer_qty - flt(qty)),3) <= 0.001:
					frappe.throw(_(f'Item {item_name} of qty {flt(qty)} entered in delivery items at row {idx} was mismatched with PO supplied items of qty {transfer_qty}'))
			supplied_items.pop(item_name)
		if supplied_items:
			unmatched_supplied_items = ','.join(supplied_items.keys())
			frappe.throw(_(f'Purchase order supplied items {unmatched_supplied_items} was not found in delivery items entered'))
		po.submit()
		return po

	def validate_delivery(self):
		is_negative_stock_allowed = frappe.db.get_single_value("Stock Settings","allow_negative_stock")
		for item in self.items:
			if item.quantity > item.available_quantity and not is_negative_stock_allowed:
				frappe.throw(_(f'Cannot deliver more than we have for {item.item_code}'))

			if item.deliver_later and not item.delivery_location:
				frappe.throw(_(f'Mention <b> Delivery Location </b> to deliver later for {item.pf_item_code}'))
	
	def get_dc_item(self):
		dc_item_list = []
		for item in self.items:
			dc_item = {}
			dc_item['item'] = item.item_code
			dc_item['idx'] = item.idx
			dc_item['qty'] = item.quantity
			dc_item_list.append(dc_item)
		return dc_item_list

	def get_supplied_items_reserve_warehouse(self):
		item_reserve_warehouse_location = {}
		for item in self.items:
			if item.delivery_location:
				reserver_warehouse = frappe.db.get_value("Warehouse", {
											'location': item.delivery_location, 'lot': self.lot, 'warehouse_type': "Actual"}, 'name')
				item_reserve_warehouse_location[item.item_code] = reserver_warehouse
		
		return item_reserve_warehouse_location

def get_stock_dict(new_po):
	rm_items = []
	for item in new_po.supplied_items:
		item_list = {}
		item_list['name'] = item.name
		item_list['item_code'] = item.main_item_code
		item_list['rm_item_code'] = item.rm_item_code
		item_list['item_name'] = item.rm_item_code
		item_list['qty'] = item.required_qty
		item_list['warehouse'] = item.reserve_warehouse
		item_list['rate'] = item.rate
		item_list['amount'] = item.amount
		item_list['stock_uom'] = item.stock_uom
		rm_items.append(item_list)
	stock_dict = make_rm_stock_entry(new_po.name, json.dumps(rm_items))
	return stock_dict

def get_grouping_params(process):
	gp_list = {
		'Raw Material': [
			{
				"dimension": (None, None),
				"group_by": [],
				"attribute_list": []
			}
		],
		'Knitting': [
			{
				"dimension": ('Dia', None),
				"group_by": ['Knitting Type', 'Yarn Category'],
				"attribute_list": ['Dia', 'Knitting Type', 'Yarn Category', 'Yarn Count', 'Yarn Shade']
			},
			{
				"dimension": (None, None),
				"group_by": [],
				"attribute_list": ['Yarn Category', 'Yarn Count', 'Yarn Shade']
			},
		],
		'Dyeing': [
			{
				"dimension": ('Dia', None),
				"group_by": [],
				"attribute_list": ['Dia', 'Knitting Type', 'Yarn Category', 'Yarn Count', 'Yarn Shade']
			},
			{
				"dimension": ('Dia', 'Apparelo Colour'),
				"group_by": ['Knitting Type'],
				"attribute_list": ['Dia', 'Knitting Type', 'Yarn Category', 'Yarn Count', 'Yarn Shade', 'Apparelo Colour']
			}
		],
		'Bleaching': [
			{
				"dimension": ('Dia', None),
				"group_by": [],
				"attribute_list": ['Dia', 'Knitting Type', 'Yarn Category', 'Yarn Count', 'Yarn Shade']
			},
			{
				"dimension": ('Dia', 'Apparelo Colour'),
				"group_by": ['Knitting Type'],
				"attribute_list": ['Dia', 'Knitting Type', 'Yarn Category', 'Yarn Count', 'Yarn Shade', 'Apparelo Colour']
			}
		],
		'Compacting': [
			{
				"dimension": ('Dia', 'Apparelo Colour'),
				"group_by": ['Knitting Type'],
				"attribute_list": ['Dia', 'Knitting Type', 'Yarn Category', 'Yarn Count', 'Yarn Shade', 'Apparelo Colour']
			}
		],
		'Cutting': [
			{
				"dimension": ('Dia', 'Apparelo Colour'),
				"group_by": ['Knitting Type'],
				"attribute_list": ['Dia', 'Knitting Type', 'Yarn Category', 'Yarn Count', 'Yarn Shade', 'Apparelo Colour']
			},
			{
				"dimension": ('Part', 'Apparelo Size'),
				"group_by": [],
				"attribute_list": ['Apparelo Colour', 'Apparelo Size', 'Part', 'Apparelo Style']
			},
			{
				"dimension": ('Part', 'Apparelo Size'),
				"group_by": [],
				"attribute_list": ['Apparelo Colour', 'Apparelo Size', 'Part']
			}
		],
		'Label Fusing': [
			{
				"dimension": ('Part', 'Apparelo Size'),
				"group_by": [],
				"attribute_list": ['Apparelo Colour', 'Apparelo Size', 'Part', 'Apparelo Style']
			},
			{
				"dimension": ('Part', 'Apparelo Size'),
				"group_by": [],
				"attribute_list": ['Apparelo Colour', 'Apparelo Size', 'Part']
			}
		],
		'Stitching': [
			{
				"dimension": ('Part', 'Apparelo Size'),
				"group_by": [],
				"attribute_list": ['Apparelo Colour', 'Apparelo Size', 'Part', 'Apparelo Style']
			},
			{
				"dimension": ('Part', 'Apparelo Size'),
				"group_by": [],
				"attribute_list": ['Apparelo Colour', 'Apparelo Size', 'Part']
			},
			{
				"dimension": ('Apparelo Colour', 'Apparelo Size'),
				"group_by": [],
				"attribute_list": ['Apparelo Colour', 'Apparelo Size']
			}
		],
		'Ironing': [
			{
				"dimension": ('Apparelo Colour', 'Apparelo Size'),
				"group_by": [],
				"attribute_list": ['Apparelo Colour', 'Apparelo Size']
			}
		],
		'Packing': [
			{
				"dimension": (None, 'Apparelo Size'),
				"group_by": [],
				"attribute_list": ['Apparelo Size']
			}
		]
	}
	return gp_list[process] if process in gp_list else []

@frappe.whitelist()
def get_location_based_address(location,company):
	address_list = frappe.get_list("Address", filters={'location': ['in',location],'link_doctype':['in','Company'],'link_name':['in',company]}, fields=["name"])
	location_based_address = None
	if address_list:
		location_based_address = address_list[0]['name']
	return location_based_address

@frappe.whitelist()
def get_supplier_based_address(supplier):
	address = frappe.db.sql(
		'SELECT dl.parent '
		'from `tabDynamic Link` dl join `tabAddress` ta on dl.parent=ta.name '
		'where '
		'dl.link_doctype=%s '
		'and dl.link_name=%s '
		'and dl.parenttype="Address" '
		'and ifnull(ta.disabled, 0) = 0 and'
		'(ta.address_type="Shipping" or ta.is_shipping_address=1) '
		'order by ta.is_shipping_address desc, ta.address_type desc limit 1',
		("Supplier", supplier)
	)
	if address:
		return address[0][0]
	else:
		return ''

@frappe.whitelist()
def get_supplier(doctype, txt, searchfield, start, page_len, filters):
	supplier_list = frappe.get_all('Supplier_Process', {'processes': filters['supplier_process.processes']}, 'parent')
	suppliers = []
	for supplier in supplier_list:
		suppliers.append([supplier['parent']])
	return suppliers

def make_item_fields(update=True):
	# todo: combine with make_custom_fields if possible
	custom_fields = {'Item': [
		{
			"fieldname": "print_code",
			"fieldtype": "Data",
			"label": "PF Item Code",
		}
	]}
	create_custom_fields(
		custom_fields, ignore_validate=frappe.flags.in_patch, update=update)


def make_custom_fields(update=True):
	custom_fields = {'Supplier': [
		{
			"fieldname": "supplier_process",
			"fieldtype": "Table",
			"label": "Supplier Process",
			"options": "Supplier_Process"
		}
	],
		'BOM': [
		{
			"fieldname": "process",
			"fieldtype": "Link",
			"label": "Process",
			"options": "Multi Process"
		}
	],
		'Purchase Order': [
		{
			"fieldname": "dc",
			"fieldtype": "Link",
			"label": "DC",
			"options": "DC"
		},
		{
			"fieldname": "lot",
			"fieldtype": "Link",
			"label": "Lot",
			"options": "Lot Creation"
		}
	]
	}
	create_custom_fields(
		custom_fields, ignore_validate=frappe.flags.in_patch, update=update)


@frappe.whitelist()
def get_ipd_item(doc):
	if isinstance(doc, string_types):
		doc = frappe._dict(json.loads(doc))

	doc['items'] = []

	lot = doc.get('lot')
	if not frappe.get_doc('Lot Creation', lot).docstatus:
		frappe.throw(_(f'Lot {lot} is not yet submitted'))

	dc_process = doc.get('process_1')
	apparelo_process = frappe.get_doc("Apparelo Process", dc_process)
	location = doc.get('location')

	lot_ipd = frappe.db.get_value(
		'Lot Creation', {'name': lot}, 'item_production_detail')
	ipd_bom_mapping = frappe.db.get_value(
		"IPD BOM Mapping", {'item_production_details': lot_ipd})
	boms = frappe.get_doc(
		'IPD BOM Mapping', ipd_bom_mapping).get_process_boms(dc_process)

	in_delivery_items = frappe.get_list("BOM Item", filters={'parent': [
										'in', boms]}, group_by='item_code', fields='item_code')
	from erpnext.stock.dashboard import item_dashboard
	dc_warehouse = frappe.db.get_value(
		"Warehouse", {'location': location, 'lot': lot, 'warehouse_type': 'Actual'}, 'name')
	items_to_be_sent = []
	for item in in_delivery_items:
		data = item_dashboard.get_data(
			item_code=item.item_code, warehouse=dc_warehouse)
		if len(data):
			item['available_quantity'] = data[0]['actual_qty']
			item_detail = frappe.get_doc('Item', item.item_code)
			item['primary_uom'] = item_detail.stock_uom
			item['secondary_uom'] = apparelo_process.in_secondary_uom
			item['pf_item_code'] = item_detail.print_code
			items_to_be_sent.append(item)
	return items_to_be_sent


@frappe.whitelist()
def get_expected_items_in_return(doc, items_to_be_sent=None, use_delivery_qty=False):
	if isinstance(doc, string_types):
		doc = frappe._dict(json.loads(doc))

	lot = doc.get('lot')
	dc_process = doc.get('process_1')
	apparelo_process = frappe.get_doc("Apparelo Process", dc_process)
	lot_ipd = frappe.db.get_value(
		'Lot Creation', {'name': lot}, 'item_production_detail')

	ipd_bom_mapping = frappe.db.get_value(
		'IPD BOM Mapping', {'item_production_details': lot_ipd})
	ipd_item_mapping = frappe.get_doc(
		"IPD Item Mapping", {'item_production_details': lot_ipd})
	boms = frappe.get_doc(
		'IPD BOM Mapping', ipd_bom_mapping).get_process_boms(dc_process)
	items_to_be_received = frappe.get_list('BOM', filters={
										   'name': ['in', boms]}, group_by='item', fields=['item', 'name as bom'])

	receivable_list = {}
	item_mapping_validator = [x["item"] for x in frappe.get_list(
		"Item Mapping", {"parent": ipd_item_mapping.name, "process_1": dc_process}, "item")]
	items_to_be_received_with_removed_invalids_list = []
	for item_to_be_received in items_to_be_received:
		# Bringing in this condition for cutting to handle the combined parts.
		if item_to_be_received['item'] in item_mapping_validator:
			receivable_list[item_to_be_received['item']] = 0
			items_to_be_received_with_removed_invalids_list.append(
				item_to_be_received)

	items_to_be_received = items_to_be_received_with_removed_invalids_list

	lot_items = frappe.get_list('Lot Creation Plan Item', filters={
								'parent': lot}, fields=['item_code', 'planned_qty', 'bom_no', 'stock_uom'])
	expect_return_items_at = frappe.db.get_value(
		'Warehouse', {'warehouse_name': f'{lot}-{doc.get("expect_return_items_at")}'}, 'name')
	# Invoke
	receivable_list = get_receivable_list_values(
		lot_items, receivable_list, expect_return_items_at)

	percentage_in_excess = frappe.db.get_value(
		'Lot Creation', lot, 'percentage')
	if percentage_in_excess:
		percentage_in_excess = (flt(percentage_in_excess) / 100)

	for item_to_be_received in items_to_be_received:
		item = item_to_be_received['item']
		stock_uom = frappe.db.get_value('Item', item, 'stock_uom')
		if frappe.db.get_value('UOM', stock_uom, 'must_be_whole_number'):
			receivable_list[item] = int(receivable_list[item] + (receivable_list[item] * percentage_in_excess))
		else:
			receivable_list[item] = receivable_list[item] + (receivable_list[item] * percentage_in_excess)

		item_to_be_received['raw_materials'] = frappe.get_list('BOM Item', filters={'parent': item_to_be_received['bom']}, fields=['item_code', 'uom', 'qty', f'"{receivable_list[item]}" as req', 'conversion_factor'])

	# Stock validation starts
	if not items_to_be_sent:
		items_to_be_sent = doc.get('items')

	for in_stock_item in items_to_be_sent:
		in_stock_item_consumable_indexes = []
		for i, item_to_be_received in enumerate(items_to_be_received):
			for rm in item_to_be_received['raw_materials']:
				if rm['item_code'] == in_stock_item['item_code']:
					if rm['uom'] == in_stock_item['primary_uom'] or get_uom_conv_factor(rm['uom'], in_stock_item['primary_uom']):
						in_stock_item_consumable_indexes.append(i)
					else:
						frappe.throw(_(f"Items expected in return and delivery have different UOMs"))
		
		if len(in_stock_item_consumable_indexes) == 0:
			frappe.throw(_(f"{in_stock_item} is not used to manufacture any of the items. Do no supply it"))

		total = 0
		for stock_item_consumable_index in in_stock_item_consumable_indexes:
			qty = receivable_list[items_to_be_received[stock_item_consumable_index]['item']]
			for rm in items_to_be_received[stock_item_consumable_index]['raw_materials']:
				if rm['item_code'] == in_stock_item['item_code']:
					if rm['uom'] == in_stock_item['primary_uom']:
						qty = rm['qty'] * qty
						break
					elif get_uom_conv_factor(rm['uom'], in_stock_item['primary_uom']):
						qty = (rm['qty'] * get_uom_conv_factor(rm['uom'], in_stock_item['primary_uom'])) * qty
						break
			total += qty

		if total == 0:
			continue

		for stock_item_consumable_index in in_stock_item_consumable_indexes:
			for i, rm in enumerate(items_to_be_received[stock_item_consumable_index]['raw_materials']):
				if use_delivery_qty:
					supply_qty = (flt(rm['req']) * in_stock_item['quantity'])/total
				else:
					supply_qty = (flt(rm['req']) * in_stock_item['available_quantity'])/total

				if frappe.db.get_value('UOM', rm['uom'], 'must_be_whole_number'):
					supply_qty = int(math.floor(supply_qty))

				# If we have in excess, we will make in excess.
				# if supply_qty > rm['req']:
				# 	supply_qty = rm['req']

				items_to_be_received[stock_item_consumable_index]['raw_materials'][i]['supply_qty'] = supply_qty

	lot_ipd_doc = frappe.get_doc("Item Production Detail", lot_ipd)
	for item_to_be_received in items_to_be_received:
		item = frappe.get_doc('Item', item_to_be_received['item'])
		item_to_be_received['item_code'] = item_to_be_received['item']
		item_to_be_received['qty'] = receivable_list[item_to_be_received['item_code']]

		for attr in item.attributes:
			if attr.attribute == "Apparelo Size":
				item_to_be_received['Apparelo Size'] = attr.attribute_value
			if attr.attribute == "Dia":
				item_to_be_received['Dia'] = attr.attribute_value
			if attr.attribute == "Apparelo Colour":
				item_to_be_received['Apparelo Colour'] = attr.attribute_value

		# TODO: What will happen if an item has been made out of multiple raw materials?
		for rm in item_to_be_received['raw_materials']:
			# if item_to_be_received['qty'] >= rm['supply_qty']:
			if 'supply_qty' in rm:
				item_to_be_received['qty'] = rm['supply_qty']
			else:
				item_to_be_received['qty'] = 0
		
		if frappe.db.get_value('UOM', item.stock_uom, 'must_be_whole_number'):
			item_to_be_received['qty'] = int(item_to_be_received['qty'])
		ipd_process_index_of_item = -1
		for item_mappping in ipd_item_mapping.item_mapping:
			if item_mappping.item == item.item_code:
				ipd_process_index_of_item = item_mappping.ipd_process_index
				break
		if ipd_process_index_of_item == -1:
			frappe.throw(
				_(f"Item:{item.item_code} not found in IPD Item Mapping"))
		item_to_be_received['additional_parameters'] = get_additional_params(
			lot_ipd_doc.processes, ipd_process_index_of_item)

		item_to_be_received['pf_item_code'] = item.print_code if item.print_code != None and item.print_code != '' else item_to_be_received['item_code']
		item_to_be_received['uom'] = item.stock_uom
		item_to_be_received['secondary_uom'] = apparelo_process.out_secondary_uom

		if not use_delivery_qty:
			item_to_be_received['projected_qty'] = item_to_be_received['qty']
			item_to_be_received['qty'] = 0
	if 'Dia' in item_to_be_received:
		if 'Apparelo Colour' in item_to_be_received:
			items_to_be_received = sorted(sorted(items_to_be_received, key = lambda i: i['Dia']), key = lambda i: i['Apparelo Colour'])
		else:
			items_to_be_received = sorted(items_to_be_received, key = lambda i: i['Dia'])
	if 'Apparelo Size' in item_to_be_received:
		items_to_be_received = sorted(items_to_be_received, key = lambda i: i['Apparelo Size'])

	return items_to_be_received


def get_receivable_list_values(lot_items, receivable_list, planned_warehouse=None):
	po_items = []
	company = get_default_company()
	for lot_item in lot_items:
		po_item = {}
		po_item['warehouse'] = planned_warehouse
		po_item['stock_uom'] = frappe.db.get_value(
			'Item', lot_item['item_code'], 'stock_uom')
		po_item['item_code'] = lot_item['item_code']
		po_item['planned_qty'] = lot_item['planned_qty']
		po_item['bom_no'] = lot_item['bom_no']
		po_items.append(po_item)

	# Using the production plan function doing the complete traversal of BOM while calculating the
	# required quantity in the receivable list. There is a scope to improve this if we can stop at
	# arriving the receivable list.
	while True:
		if len(po_items) > 0:
			input = {
				'company': company,
				'po_items': po_items
			}
			mr_items = get_items_for_material_requests(json.dumps(input))
		else:
			break
		po_items = []
		for mr_item in mr_items:
			if mr_item['item_code'] in receivable_list:
				receivable_list[mr_item['item_code']] += mr_item['quantity']

			bom_no = frappe.db.get_value(
				'Item', mr_item['item_code'], 'default_bom')
			po_item = {}
			if bom_no:
				po_item['bom_no'] = bom_no
				po_item['item_code'] = mr_item['item_code']
				po_item['planned_qty'] = mr_item['quantity']
				po_item['stock_uom'] = mr_item['stock_uom']
				po_item['warehouse'] = planned_warehouse
				po_items.append(po_item)

	return receivable_list


def get_additional_params(ipd_processes, ipd_process_index):
	ipd_process_array_index = int(ipd_process_index)-1
	if ipd_processes[ipd_process_array_index].idx == int(ipd_process_index):
		process_name = ipd_processes[ipd_process_array_index].process_name
		process_record = ipd_processes[ipd_process_array_index].process_record
		process_doc = frappe.get_doc(process_name, process_record)
		if process_doc.additional_information:
			additional_parameters_string = ''
			for info in process_doc.additional_information:
				additional_parameters_string += f'{info.parameter} : {info.value}\n'
			return additional_parameters_string
		else:
			return None
	else:
		frappe.throw(_("Unexpected error in getting additional params. IPD processes list was probably not sorted during fetch."))

@frappe.whitelist()
def get_delivery_qty_from_return_materials(doc):
	if isinstance(doc, string_types):
		doc = frappe._dict(json.loads(doc))

	po_items = []
	company = get_default_company()

	items = doc.get('return_materials')
	for item in items:
		po_item = {}
		po_item['stock_uom'] = item['uom']
		po_item['item_code'] = item['item_code']
		po_item['planned_qty'] = item['qty']
		po_item['bom_no'] = item['bom']

		if po_item['planned_qty'] != 0:
			po_items.append(po_item)

	input = {
		'company': company,
		'po_items': po_items
	}
	required_raw_materials = get_items_for_material_requests(json.dumps(input))
	delivery_items = doc.get('items')
	for delivery_item in delivery_items:
		for required_raw_material in required_raw_materials:
			if required_raw_material['item_code'] == delivery_item['item_code'] \
				and required_raw_material['uom'] == delivery_item['primary_uom']:
				delivery_item['quantity'] = required_raw_material['quantity']
	
	return delivery_items

@frappe.whitelist()
def make_dc(doc):
	items_to_be_sent = get_ipd_item(doc)
	items_to_be_received = get_expected_items_in_return(doc, items_to_be_sent=items_to_be_sent, use_delivery_qty=False)
	dc = {
		'items': items_to_be_sent,
		'return_materials': items_to_be_received
	}

	return dc

@frappe.whitelist()
def calculate_expected_qty_from_delivery_qty(doc):
	raw_doc = doc
	if isinstance(doc, string_types):
		doc = frappe._dict(json.loads(doc))

	for item in doc.get('items'):
		if not 'quantity' in item or item['quantity'] == 0:
			frappe.throw(_(f'Enter delivery quantity for {item["item_code"]}'))
	
	items_to_be_received = get_expected_items_in_return(raw_doc, items_to_be_sent=doc.get('items'), use_delivery_qty=True)

	return_items = doc.get('return_materials')
	for return_item in return_items:
		for item_to_be_received in items_to_be_received:
			if item_to_be_received['item_code'] == return_item['item_code']:
				return_item['qty'] = item_to_be_received['qty']

	return return_items

@frappe.whitelist()
def duplicate_values(doc):
	dc_items = []
	if isinstance(doc, string_types):
		doc = frappe._dict(json.loads(doc))
	for item in doc.get('items'):
		field_dict = {'Available Qty':'available_quantity','Delivery Qty':'quantity','Secondary Qty':'secondary_qty'}
		if doc.from_field in field_dict and doc.to_field in field_dict:
			item_dict = {"pf_item_code":item['pf_item_code'],"item_code":item['item_code'],field_dict[doc.from_field]:item[field_dict[doc.from_field]],field_dict[doc.to_field]:item[field_dict[doc.from_field]],"primary_uom":item['primary_uom'],"secondary_uom":item['secondary_uom']}
			if item['deliver_later']:
				item_dict["deliver_later"] = item['deliver_later']
				item_dict["delivery_location"] = item['delivery_location']
		field_dict.pop(doc.from_field)
		field_dict.pop(doc.to_field)
		if list(field_dict.values())[0] in item:
			item_dict[list(field_dict.values())[0]]	= item[list(field_dict.values())[0]]
		dc_items.append(item_dict)
	return dc_items

@frappe.whitelist()
def delete_unavailable_delivery_items(doc):
	dc_available_items = []
	if isinstance(doc, string_types):
		doc = frappe._dict(json.loads(doc))
	for item in doc.get('items'):
		item_dict={}
		if item['quantity']!=0:
			item_dict = {"pf_item_code":item['pf_item_code'],"item_code":item['item_code'],"available_quantity":item['available_quantity'],"quantity":item['quantity'],"primary_uom":item['primary_uom'],"secondary_qty":item['secondary_qty'],"secondary_uom":item['secondary_uom']}
			if item['deliver_later']:
				item_dict["deliver_later"] = item['deliver_later']
				item_dict["delivery_location"] = item['delivery_location']
		if item_dict:
			dc_available_items.append(item_dict)
	return dc_available_items

@frappe.whitelist()
def delete_unavailable_return_items(doc):
	available_return_items = []
	if isinstance(doc, string_types):
		doc = frappe._dict(json.loads(doc))
	for item in doc.get('return_materials'):
		item_dict={}
		if item['qty']!=0:
			item_dict = {"pf_item_code":item['pf_item_code'],"item_code":item['item_code'],"bom":item['bom'],"qty":item['qty'],"projected_qty":item['projected_qty'],"uom":item['uom'],"secondary_qty":item['secondary_qty']}
			if 'secondary_uom' in item:
				item_dict["secondary_uom"] = item['secondary_uom']
			if 'additional_parameters' in item:
				item_dict["additional_parameters"] = item['additional_parameters']
		if item_dict:
			available_return_items.append(item_dict)
	return available_return_items

@frappe.whitelist()
def make_entry(doc):
	return_items_after_entry = []
	if isinstance(doc, string_types):
		doc = frappe._dict(json.loads(doc))
	items_to_be_sent = get_ipd_item(doc)
	items_to_be_received = get_expected_items_in_return(doc, items_to_be_sent=items_to_be_sent, use_delivery_qty=False)
	size = doc.size
	colour = doc.colour
	piece_count = doc.piece_count 
	ipd = frappe.db.get_value('Lot Creation',{'name': doc.get('lot')},'item_production_detail')
	process_record_list = frappe.get_list("Item Production Detail Process",{'parent': ipd,'process_name':'Stitching'},'process_record')
	if len(process_record_list)>1:
		frappe.throw(_(f'Unable to proceed with more than one stitching process record'))
	else:
		colour_mappings = frappe.get_list("Stitching",filters={'name':['in',[process_record_list[0]['process_record']]]},fields=["`tabStitching Colour Mapping`.part","`tabStitching Colour Mapping`.piece_colour","`tabStitching Colour Mapping`.part_colour"])
		parts_per_pieces = frappe.get_list("Stitching",filters={'name':['in',[process_record_list[0]['process_record']]]},fields=["`tabStitching Parts Per Piece`.part","`tabStitching Parts Per Piece`.qty"])
		for item in items_to_be_received:
			item_dict={}
			count=0
			item_doc = frappe.get_doc('Item', item['item_code'])
			attribute_set = get_item_attribute_set(list(map(lambda x: x.attributes, [item_doc])))
			for colour_mapping in colour_mappings:
				for parts_per_piece in parts_per_pieces:
					if attribute_set["Part"][0] == parts_per_piece.part and attribute_set["Part"][0] == colour_mapping.part and attribute_set['Apparelo Size'][0] == size:
						if colour_mapping.piece_colour == colour and colour_mapping.part_colour == attribute_set["Apparelo Colour"][0]:
								count+=1
								piece_qty = parts_per_piece.qty
			if count==1:
				item_dict = {"pf_item_code":item['pf_item_code'],"item_code":item['item_code'],"bom":item['bom'],"qty":piece_count*piece_qty,"projected_qty":item['projected_qty'],"uom":item['uom'],"secondary_uom":item['secondary_uom']}
				if 'additional_parameters' in item:
					item_dict["additional_parameters"] = item['additional_parameters']
				return_items_after_entry.append(item_dict)
	return return_items_after_entry

@frappe.whitelist()
def make_grn(source_name, target_doc=None):
	doc = get_mapped_doc("DC", source_name,	{
		"DC": {
			"doctype": "GRN",
			"field_map": {
				"supplier": "supplier",
				"lot": "lot",
				"expect_return_items_at": "location",
				"name": "against_document",
				"doctype": "against_type",
				"return_materials": "return_materials"
			}
			}
		}, target_doc)
	return doc

@frappe.whitelist()
def divide_total_quantity(doc):
	dc_item = []
	total_qty = 0
	matching_item_list = []
	if isinstance(doc, string_types):
		doc = frappe._dict(json.loads(doc))
	attribute = doc.get('attribute')
	attribute_value = doc.get('attribute_value')
	total_delivered_qty = doc.get('total_quantity_delivered')
	if total_delivered_qty:
		for row in doc['items']:
			item_doc = frappe.get_doc("Item",row['item_code'])
			attribute_set = get_item_attribute_set(list(map(lambda x: x.attributes,[item_doc])))
			if attribute_set[attribute][0] == attribute_value:
				total_qty += row['available_quantity']
				matching_item_list.append(row['item_code'])
		for row in doc['items']:
			if row['item_code'] in matching_item_list:
				if total_delivered_qty>total_qty:
					remaining_qty = total_delivered_qty - total_qty
					row['quantity'] = row['available_quantity'] + (remaining_qty/total_qty)*row['available_quantity']
				else:
					row['quantity'] = (total_delivered_qty/total_qty)*row['available_quantity']
				dc_item.append({"item_code":row['item_code'],"primary_uom":row['primary_uom'],"available_quantity":row['available_quantity'],"pf_item_code":row['pf_item_code'],"secondary_uom":row['secondary_uom'],"quantity":row['quantity']})
			else:
				if 'quantity' in row:
					dc_item.append({"item_code":row['item_code'],"primary_uom":row['primary_uom'],"available_quantity":row['available_quantity'],"pf_item_code":row['pf_item_code'],"secondary_uom":row['secondary_uom'],"quantity":row['quantity']})
				else:
					dc_item.append({"item_code":row['item_code'],"primary_uom":row['primary_uom'],"available_quantity":row['available_quantity'],"pf_item_code":row['pf_item_code'],"secondary_uom":row['secondary_uom']})
	return dc_item