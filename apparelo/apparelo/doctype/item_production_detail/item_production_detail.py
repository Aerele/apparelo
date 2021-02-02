# -*- coding: utf-8 -*-
# Copyright (c) 2019, Aerele Technologies Private Limited and contributors
# For license information, please see license.txt

from __future__ import unicode_literals
import frappe
import json
from frappe import _
from erpnext import get_default_company, get_default_currency
from frappe.model.document import Document
from apparelo.apparelo.doctype.ipd_item_mapping.ipd_item_mapping import ipd_item_mapping
from apparelo.apparelo.doctype.ipd_bom_mapping.ipd_bom_mapping import ipd_bom_mapping
from frappe.utils import comma_and,get_link_to_form
from collections import Counter
from frappe.core.page.background_jobs.background_jobs import get_info
from frappe.utils.background_jobs import enqueue
from six import string_types

class ItemProductionDetail(Document):
	def before_insert(self):
		if self.ipd_submission_done:
			self.ipd_submission_done = 0
	def on_submit(self):
		if self.ipd_submission_done:
			return
		self.validate_process_records()

		enqueued_jobs = [d.get("job_name") for d in get_info()]
		if self.name in enqueued_jobs:
			frappe.throw(
				_("Submission already in progress. Please wait for sometime.")
			)
		else:
			enqueue(
				submit_ipd,
				queue="default",
				timeout=6000,
				event="ipd_submission",
				job_name=self.name,
				ipd=self.name
			)
			frappe.throw(
				_("Submission job added to queue. Please check after sometime.")
			)

	def create_item_templates(self):
		template_item_codes_from_stitching = {"Stitching":" Stitched Cloth", "Checking":" Checked Cloth","Ironing":" Ironed Cloth"}
		template_item_codes_from_cutting = {"Cutting":" Cut Cloth", "Label Fusing": " Labeled Cloth", "Piece Printing": " Printed Cloth"}
		template_item_codes_for_set_items = {"Stitching":" Stitched Cloth", "Checking":" Checked Cloth"}
		for process in self.processes:
			if process.process_name in template_item_codes_from_stitching.keys():
				item_code = self.item+template_item_codes_from_stitching[process.process_name]
				if self.enable_set_item:
					if process.process_name in template_item_codes_for_set_items.keys():
						attribute = [
								{
									"attribute" : "Apparelo Colour"
								},
								{
									"attribute" : "Part"
								},
								{
									"attribute" : "Apparelo Size"
								}
							]
					else:
						attribute = [
							{
								"attribute" : "Apparelo Colour"
							},
							{
								"attribute" : "Apparelo Size"
							}
						]					
				else:
					attribute = [
							{
								"attribute" : "Apparelo Colour"
							},
							{
								"attribute" : "Apparelo Size"
							}
						]
				if not frappe.db.exists("Item",item_code):
					frappe.get_doc({
						"doctype": "Item",
						"item_code": item_code,
						"item_name": item_code,
						"description":item_code,
						"item_group": "Sub Assemblies",
						"stock_uom" : "Nos",
						"has_variants" : "1",
						"variant_based_on" : "Item Attribute",
						"is_sub_contracted_item": "1",
						"attributes" : attribute
					}).save()
			elif process.process_name in template_item_codes_from_cutting.keys():
				item_code = self.item+template_item_codes_from_cutting[process.process_name]
				if self.based_on_style == 0:
					attribute = [
							{
								"attribute" : "Apparelo Colour"
							},
							{
								"attribute" : "Part"
							},
							{
								"attribute" : "Apparelo Size"
							}
						]
				else:
					attribute = [
							{
								"attribute" : "Apparelo Colour"
							},
							{
								"attribute" : "Part"
							},
							{
								"attribute" : "Apparelo Size"
							},
							{
								"attribute" : "Apparelo Style"
							}
						]
				if not frappe.db.exists("Item",item_code):
					frappe.get_doc({
					"doctype": "Item",
					"item_code": item_code,
					"item_name": item_code,
					"description":item_code,
					"item_group": "Sub Assemblies",
					"stock_uom" : "Nos",
					"has_variants" : "1",
					"variant_based_on" : "Item Attribute",
					"is_sub_contracted_item": "1",
					"attributes" : attribute
					}).save()
				

	def validate_process_records(self):
		count = 0
		link =''
		for process in self.processes:
			doc_type= frappe.get_doc(process.process_name, process.process_record)
			if not doc_type.docstatus:
				link += f'{get_link_to_form(process.process_name,process.process_record)} , '
				count +=1
		if count != 0:
			frappe.throw(_(f"The process {link} is not submitted"))

	def submit_all_process_records(self):
		for process in self.processes:
			process_doc = frappe.get_doc(process.process_name, process.process_record)
			if not process_doc.docstatus:
				try:
					process_doc.submit()
				except:
					link = get_link_to_form(process.process_name, process.process_record)
					frappe.throw(_(f"Unable to submit process {link}"))
					frappe.log_error(frappe.get_traceback())
					return
		frappe.msgprint(_("""Process records submitted"""))
	def create_process_details(self):
		common_process_list=['Dyeing', 'Roll Printing', 'Bleaching', 'Ironing', 'Checking', 'Packing']
		ipd = []
		attribute_set={}
		final_attribute={}
		cutting_attribute={}
		item_size=[]
		colour=[]
		existing_item_list = []
		style=[]
		final_process=self.final_process
		for final_size in self.size:
			item_size.append(final_size.size)
		for final_colour in self.colour:
			colour.append(final_colour.colour)
		if self.style:
			for final_style in self.style:
				style.append(final_style.style)
			final_attribute["Apparelo Style"]=style
		final_attribute["Apparelo Colour"]=colour
		final_attribute["Apparelo Size"]=item_size
		piece_count=len(colour)
		for process in self.processes:
			try:
				process_variants = {}
				if process.process_name == 'Knitting':
					process_variants['process'] = 'Knitting'
					process_variants['ipd']=self.name
					process_variants['index']=process.idx
					process_variants['input_index']=''
					process_variants['input_item']=[process.input_item]
					if process.input_item:
						process_variants['process_record'] = process.process_record
						knitting_doc = frappe.get_doc('Knitting', process.process_record)
						variants = knitting_doc.create_variants([process.input_item])
						process_variants['variants'] = list(set(variants))
						boms=knitting_doc.create_boms([process.input_item], variants, attribute_set,item_size,colour,piece_count)
						process_variants['BOM']=list(set(boms))
						ipd.append(process_variants)
					elif process.input_index:
						pass
					continue

				if process.process_name in common_process_list:
					process_variants['process'] = process.process_name
					process_variants['ipd']=self.name
					process_variants['index']=process.idx
					if process.input_item:
						pass
					if process.ipd_name:
						ipd.append(get_process_variants(process_variants,ipd,process,final_attribute,item_size,colour,piece_count,self.item,final_process))
					elif process.input_index:
						ipd.append(get_default_process_variants(self.name,ipd,process,process_variants,attribute_set,item_size,colour,piece_count,self.item,final_process))
					continue
				if process.process_name == 'Steaming':
					process_variants['process'] = 'Steaming'
					process_variants['ipd']=self.name
					process_variants['index']=process.idx
					if process.input_item:
						pass
					elif process.input_index:
						variants=[]
						boms=[]
						input_items_= []
						input_indexs = process.input_index.split(',')
						process_variants['input_index']=process.input_index
						for pro in ipd:
							for input_index in input_indexs:
								input_items=[]
								if str(pro['index'])==input_index:
									input_items=pro['variants']
									input_items_.extend(input_items)
									process_variants['process_record'] = process.process_record
									steaming_doc = frappe.get_doc('Steaming', process.process_record)
									variant,attribute_set = steaming_doc.create_variants(input_items)
									variants.extend(variant)
									boms.extend(steaming_doc.create_boms(input_items, variants, attribute_set,item_size,colour,piece_count))
						process_variants['variants'] = list(set(variants))
						process_variants['BOM']=list(set(boms))
						process_variants['input_item']=list(set(input_items_))
						ipd.append(process_variants)
					continue

				if process.process_name == 'Compacting':
					process_variants['process'] = 'Compacting'
					process_variants['ipd']=self.name
					process_variants['index']=process.idx
					if process.input_item:
						pass
					elif process.input_index:
						variants=[]
						boms=[]
						input_items_= []
						input_indexs = process.input_index.split(',')
						process_variants['input_index']=process.input_index
						for pro in ipd:
							for input_index in input_indexs:
								input_items=[]
								if str(pro['index'])==input_index:
									input_items=pro['variants']
									input_items_.extend(input_items)
									process_variants['process_record'] = process.process_record
									compacting_doc = frappe.get_doc('Compacting', process.process_record)
									variant,attribute_set = compacting_doc.create_variants(input_items)
									variants.extend(variant)
									boms.extend(compacting_doc.create_boms(input_items, variants, attribute_set,item_size,colour,piece_count))
						process_variants['variants'] = list(set(variants))
						process_variants['BOM']=list(set(boms))
						process_variants['input_item']=list(set(input_items_))
						ipd.append(process_variants)
					continue

				if process.process_name == 'Cutting':
					process_variants['process'] = 'Cutting'
					process_variants['ipd']=self.name
					process_variants['index']=process.idx
					if process.input_item:
						pass
					elif process.input_index:
						new_variants=[]
						boms=[]
						input_items_= []
						input_indexs = process.input_index.split(',')
						process_variants['input_index']=process.input_index
						for pro in ipd:
							for input_index in input_indexs:
								input_items=[]
								if str(pro['index'])==input_index:
									input_items_.extend(pro['variants'])
						process_variants['process_record'] = process.process_record
						cutting_doc = frappe.get_doc('Cutting', process.process_record)
						variants,attribute_set = cutting_doc.create_variants(input_items_, item_size, self.item)
						boms,new_variants=cutting_doc.create_boms(input_items_, variants, attribute_set, item_size, colour, piece_count, process.process_record, process.idx)
						counter_attr=Counter(cutting_attribute)
						attr_set=Counter(attribute_set)
						counter_attr.update(attr_set)
						cutting_attribute=dict(counter_attr)
						for value in cutting_attribute:
							cutting_attribute[value]=list(set(cutting_attribute[value]))
						process_variants['variants'] = list(set(new_variants))
						process_variants['BOM']=boms
						process_variants['input_item']=list(set(input_items_))
						ipd.append(process_variants)
					continue
				if process.process_name == 'Piece Printing':
					process_variants['process'] = 'Piece Printing'
					process_variants['ipd']=self.name
					process_variants['index']=process.idx
					if process.input_item:
						pass
					if process.ipd_name:
						process_variants,existing_item=get_existing_process_variants(process_variants,ipd,process,cutting_attribute,item_size,colour,piece_count,self.item,final_process)
						ipd.append(process_variants)
						existing_item_list.extend(existing_item)					
					elif process.input_index:
						input_items_= []
						variants=[]
						boms=[]
						input_indexs = process.input_index.split(',')
						process_variants['input_index']=process.input_index
						for pro in ipd:
							for input_index in input_indexs:
								input_items=[]
								if str(pro['index'])==input_index:
									input_items=pro['variants']
									input_items_.extend(input_items)
						process_variants['process_record'] = process.process_record
						piece_printing_doc = frappe.get_doc('Piece Printing', process.process_record)
						variants.extend(piece_printing_doc.create_variants(input_items_, self.item))
						bom_list,existing_item = piece_printing_doc.create_boms(input_items_, variants,cutting_attribute,item_size,colour,piece_count)
						boms.extend(bom_list)
						existing_item_list.extend(existing_item)
						process_variants['variants'] = list(set(variants))
						process_variants['BOM']=list(set(boms))
						process_variants['input_item']=list(set(input_items_))
						ipd.append(process_variants)
					continue
				if process.process_name == 'Stitching':
					process_variants['process'] = 'Stitching'
					process_variants['ipd']=self.name
					process_variants['index']=process.idx
					if process.input_item:
						pass
					if process.ipd_name:
						if process.input_index:
							input_items= []
							item_list=[]
							ipd_item_name=frappe.db.get_value('IPD Item Mapping', {'item_production_details': process.ipd_name}, 'name')
							ipd_item_doc=frappe.get_doc("IPD Item Mapping",ipd_item_name)
							previous_process_index=process.ipd_process_index.split(",")
							for index in previous_process_index:
								for item_mapping in ipd_item_doc.item_mapping:
									if item_mapping.ipd_process_index==index:
										item_list.append(item_mapping.item)
							input_items.extend(item_list)
							variants=[]
							boms=[]
							input_indexs = process.input_index.split(',')
							process_variants['input_index']=process.ipd_process_index+","+process.input_index
							for pro in ipd:
								for input_index in input_indexs:
									if str(pro['index'])==input_index and pro['ipd']==self.name:
										input_items.extend(pro['variants'])
							input_items = list(set(input_items) - set(existing_item_list))
							stitching_doc = frappe.get_doc('Stitching', process.process_record)
							variants.extend(stitching_doc.create_variants(input_items,colour,self.item,final_process))
							boms.extend(stitching_doc.create_boms(input_items, variants,cutting_attribute,item_size,colour,piece_count,final_process))
							process_variants['variants'] = list(set(variants))
							process_variants['BOM']=list(set(boms))
							process_variants['input_item']=list(set(input_items))
							ipd.append(process_variants)
						else:
							ipd.append(get_process_variants(process_variants,ipd,process,cutting_attribute,item_size,colour,piece_count,self.item, final_process))
					else:
						if process.input_index:
							input_items= []
							variants=[]
							boms=[]
							input_indexs = process.input_index.split(',')
							process_variants['input_index']=process.input_index
							for pro in ipd:
								for input_index in input_indexs:
									if str(pro['index'])==input_index:
										input_items.extend(pro['variants'])
							input_items = list(set(input_items) - set(existing_item_list))
							process_variants['process_record'] = process.process_record
							stitching_doc = frappe.get_doc('Stitching', process.process_record)
							variants.extend(stitching_doc.create_variants(input_items,colour,self.item,final_process))
							boms.extend(stitching_doc.create_boms(input_items, variants,cutting_attribute,item_size,colour,piece_count,final_process))
							process_variants['variants'] = list(set(variants))
							process_variants['BOM']=list(set(boms))
							process_variants['input_item']=list(set(input_items))
							ipd.append(process_variants)
					continue
				if process.process_name == 'Label Fusing':
					process_variants['process'] = 'Label Fusing'
					process_variants['ipd']=self.name
					process_variants['index']=process.idx
					if process.input_item:
						pass
					if process.ipd_name:
						process_variants,existing_item=get_existing_process_variants(process_variants,ipd,process,cutting_attribute,item_size,colour,piece_count,self.item,final_process)
						ipd.append(process_variants)
						existing_item_list.extend(existing_item)
					elif process.input_index:
						input_items_= []
						variants=[]
						boms=[]
						input_indexs = process.input_index.split(',')
						process_variants['input_index']=process.input_index
						for pro in ipd:
							for input_index in input_indexs:
								input_items=[]
								if str(pro['index'])==input_index:
									input_items=pro['variants']
									input_items_.extend(input_items)
						process_variants['process_record'] = process.process_record
						label_fusing_doc = frappe.get_doc('Label Fusing', process.process_record)
						variants.extend(label_fusing_doc.create_variants(input_items_, self.item))
						bom_list,existing_item = label_fusing_doc.create_boms(input_items_, variants,cutting_attribute,item_size,colour,piece_count)
						boms.extend(bom_list)
						existing_item_list.extend(existing_item)
						process_variants['variants'] = list(set(variants))
						process_variants['BOM']=list(set(boms))
						process_variants['input_item']=list(set(input_items_))
						ipd.append(process_variants)
					continue
			except:
				frappe.throw(_("Exception occurred while processing {0}").format(vars(process)))

		if self.additional_flows!=[]:
			ipd=additional_process(self,ipd)
		if self.is_combined_packing:
			input_items_=[]
			process_variants = {}
			for combined_ipd in self.combined_ipds:
				item_mapping = frappe.db.get_value("IPD Item Mapping", {'item_production_details': combined_ipd.ipd})
				ipd_doc=frappe.get_doc("Item Production Detail",combined_ipd.ipd)
				variants = frappe.get_doc('IPD Item Mapping', item_mapping).get_process_variants(ipd_doc.final_process)
				input_items_.extend(variants)
			if self.process_name == 'Packing':
				process_variants['process'] = 'Packing'
				process_variants['ipd']=self.name
				process_variants['index']="C1"
				new_variants=[]
				boms=[]
				process_variants['input_index']=''
				process_variants['process_record'] = self.process_record
				packing_doc = frappe.get_doc('Packing', self.process_record)
				variants = packing_doc.create_variants(input_item_names=input_items_, colour=colour, item=self.item, final_process=final_process)
				new_variants.extend(variants)
				boms.extend(packing_doc.create_boms(input_items_, variants, colour, attribute_set=final_attribute, item_size=item_size, piece_count=piece_count, final_item=self.item, final_process=final_process))
				process_variants['variants'] = list(set(new_variants))
				process_variants['BOM']=list(set(boms))
				process_variants['input_item']=list(set(input_items_))
				ipd.append(process_variants)
			else:
				frappe.throw(_(f"Only Packing Process is Supported in Combined IPD Packing"))
		return ipd

def additional_process(self,ipd):
	items=[]
	for process in self.additional_flows:
		input_index=''
		process_variants={}
		input_item=[]
		process_variants['index']='A'+str(process.idx)
		process_variants['process']=process.process_1
		process_variants['ipd']=self.name
		process_variants['input_index']=''
		process_=frappe.get_doc("Multi Process",process.process_1)
		input_indexs=[]
		for ipd_ in ipd:
			if ipd_['process']==process_.from_process:
				input_index=ipd_['input_index']
				input_indexs.extend(input_index.split(','))
		for ipd_ in ipd:
			for in_index in input_indexs:
				if str(ipd_['index'])==in_index:
					input_=ipd_['variants']
					input_item.extend(input_)

			if ipd_['process']==process_.to_process:
				process_variants['variants']=ipd_['variants']
				process_variants['BOM']=ipd_['BOM']
		for item in input_item:
			item_={}
			item_['item']=item
			item_['qty']=0
			item_['uom']=''
			items.append(item_)
		boms=set()
		input_=set()
		for bom in process_variants['BOM']:
			item_list=[]
			bom_=frappe.get_doc("BOM",bom)
			additional_item={}
			for _item in bom_.items:
				if _item.bom_no=='':
					additional_item[_item.item_code]=0
			qty=1
			planned_qty=1
			additional_item,items_=bom_item(qty,bom,additional_item,input_item,items,planned_qty)
			for item in items_:
				if item['qty']!=0:
					input_.add(item['item'])
					item_list.append({"item_code": item['item'],"qty":item['qty'] ,"uom": item['uom']})
					item['qty']=0
					item['uom']=''
			for add_ in additional_item:
				item_list.append({"item_code": add_,"qty":additional_item[add_] ,"uom": 'Nos'})
			existing_bom = frappe.db.get_value('BOM', {'item': bom_.item,'process':process_variants['process']}, 'name')
			if not existing_bom:
				new_bom = frappe.get_doc({
					"doctype": "BOM",
					"currency": get_default_currency(),
					'process': process_variants['process'],
					"is_default":0,
					"is_active":1,
					"item": bom_.item,
					"company": get_default_company(),
					"items": item_list
				})
				new_bom.save()
				new_bom.submit()
				boms.add(new_bom.name)
			else:
				boms.add(existing_bom)
		process_variants['input_item']=list(input_)
		process_variants['BOM']=list(boms)
		ipd.append(process_variants)
	return ipd

def bom_item(qty,bom,additional_item,variants,items,planned_qty):
	bom_doc=frappe.get_doc("BOM",bom)
	bom_quantity=(bom_doc.quantity/bom_doc.quantity)*planned_qty
	for item in bom_doc.items:
		if item.uom=='Gram':
			bom_quantity=bom_quantity*item.stock_qty
		if item.uom=='Nos' and item.qty>1:
				qty=item.qty*planned_qty
		if item.bom_no=='':
			if not item.item_code in additional_item:
				additional_item[item.item_code]=0
				additional_item[item.item_code]+=item.qty*bom_quantity
			else:
				additional_item[item.item_code]+=item.qty*bom_quantity
		else:
			if item.item_code in variants:
				for bom_item_list in items:
					if item.item_code==bom_item_list['item']:
						bom_item_list['qty']+=item.qty*qty*bom_quantity
						bom_item_list['uom']=item.uom
						qty=1
			else:
				bom_item(qty,item.bom_no,additional_item,variants,items,bom_quantity)
				qty=1
	return additional_item,items


def get_boms(index,ipd_bom_doc):
	boms=[]
	for bom_mapping in ipd_bom_doc.bom_mapping:
		if bom_mapping.ipd_process_index==str(index):
			boms.append(bom_mapping.bom)
	return boms

def get_variants(index,ipd_item_doc):
	process=''
	input_item=[]
	variants=[]
	input_index=''
	ipd_name=''
	for item_mapping in ipd_item_doc.item_mapping:
		if item_mapping.ipd_process_index==str(index):
			input_index=item_mapping.input_index
			process=item_mapping.process_1
			ipd_name=item_mapping.ipd
			input_item.append(item_mapping.input_item)
			variants.append(item_mapping.item)
	return ipd_name,input_index,list(set(variants)),list(set(input_item)),process,str(index)

def get_process_variants(process_variants,ipd,process,cutting_attribute,item_size,colour,piece_count,item,final_process):
	item_list=[]
	variants=[]
	boms=[]
	process_variants['input_index']=process.ipd_process_index
	ipd_item_name=frappe.db.get_value('IPD Item Mapping', {'item_production_details': process.ipd_name}, 'name')
	ipd_item_doc=frappe.get_doc("IPD Item Mapping",ipd_item_name)
	ipd_bom_name=frappe.db.get_value('IPD BOM Mapping', {'item_production_details': process.ipd_name}, 'name')
	ipd_bom_doc=frappe.get_doc("IPD BOM Mapping",ipd_bom_name)
	previous_process_index=process.ipd_process_index.split(",")
	for index in previous_process_index:
		for item_mapping in ipd_item_doc.item_mapping:
			if item_mapping.ipd_process_index==index:
				item_list.append(item_mapping.item)
	for index in range(1,int(max(previous_process_index))+1):
		previous_variants={}
		previous_variants['ipd'],previous_variants['input_index'],previous_variants['variants'],previous_variants['input_item'],previous_variants['process'],previous_variants['index']=get_variants(index,ipd_item_doc)
		previous_variants['BOM']=list(set(get_boms(index,ipd_bom_doc)))
		if not previous_variants in ipd:
			ipd.append(previous_variants)
	process_variants['process_record'] = process.process_record
	process_doc = frappe.get_doc(process.process_name, process.process_record)
	variants.extend(process_doc.create_variants(list(set(item_list)),colour,item,final_process))
	boms.extend(process_doc.create_boms(item_list, variants,cutting_attribute,item_size,colour,piece_count,final_process))
	process_variants['variants'] = list(set(variants))
	process_variants['BOM']=list(set(boms))
	process_variants['input_item']=list(set(item_list))
	return process_variants

def get_default_process_variants(ipd_name,ipd,process,process_variants,attribute_set,item_size,colour,piece_count,item,final_process):
	input_items_= []
	variants=[]
	boms=[]
	input_indexs = process.input_index.split(',')
	process_variants['input_index']=process.input_index
	for pro in ipd:
		for input_index in input_indexs:
			input_items = []
			if str(pro['index'])==input_index and pro['ipd']==ipd_name:
				input_items=pro['variants']
				input_items_.extend(input_items)
	process_variants['process_record'] = process.process_record
	process_doc = frappe.get_doc(process.process_name, process.process_record)
	variants.extend(process_doc.create_variants(input_item_names=input_items_, colour=colour, item=item, final_process=final_process))
	boms.extend(process_doc.create_boms(input_items_, variants, colour, attribute_set=attribute_set, item_size=item_size, piece_count=piece_count, final_item=item, final_process=final_process))
	process_variants['variants'] = list(set(variants))
	process_variants['BOM']=list(set(boms))
	process_variants['input_item']=list(set(input_items_))
	return process_variants

def get_existing_process_variants(process_variants,ipd,process,cutting_attribute,item_size,colour,piece_count,item,final_process):
	item_list=[]
	variants=[]
	boms=[]
	existing_item_list=[]
	process_variants['input_index']=process.ipd_process_index
	ipd_item_name=frappe.db.get_value('IPD Item Mapping', {'item_production_details': process.ipd_name}, 'name')
	ipd_item_doc=frappe.get_doc("IPD Item Mapping",ipd_item_name)
	ipd_bom_name=frappe.db.get_value('IPD BOM Mapping', {'item_production_details': process.ipd_name}, 'name')
	ipd_bom_doc=frappe.get_doc("IPD BOM Mapping",ipd_bom_name)
	previous_process_index=process.ipd_process_index.split(",")
	for index in previous_process_index:
		for item_mapping in ipd_item_doc.item_mapping:
			if item_mapping.ipd_process_index==index:
				item_list.append(item_mapping.item)
	for index in range(1,int(max(previous_process_index))+1):
		previous_variants={}
		previous_variants['ipd'],previous_variants['input_index'],previous_variants['variants'],previous_variants['input_item'],previous_variants['process'],previous_variants['index']=get_variants(index,ipd_item_doc)
		previous_variants['BOM']=list(set(get_boms(index,ipd_bom_doc)))
		if not previous_variants in ipd:
			ipd.append(previous_variants)
	process_variants['process_record'] = process.process_record
	process_doc = frappe.get_doc(process.process_name, process.process_record)
	variants.extend(process_doc.create_variants(list(set(item_list)), item))
	bom_list, existing_item= process_doc.create_boms(item_list, variants,cutting_attribute,item_size,colour,piece_count)
	boms.extend(bom_list)
	existing_item_list.extend(existing_item)
	process_variants['variants'] = list(set(variants))
	process_variants['BOM']=list(set(boms))
	process_variants['input_item']=list(set(item_list))
	return process_variants, existing_item_list

def submit_ipd(ipd):
	try:
		ipd_doc = frappe.get_doc("Item Production Detail", ipd)
		item_templates=ipd_doc.create_item_templates()
		ipd_list=ipd_doc.create_process_details()
		ipd_item_mapping(ipd_list,ipd_doc.name,ipd_doc.item)
		ipd_bom_mapping(ipd_list,ipd_doc.name,ipd_doc.item)
		ipd_doc.ipd_submission_done = 1
		ipd_doc.docstatus = 1
		ipd_doc.save()
	except:
		error_message = frappe.get_traceback()+"\n\n IPD Name: \n"+ipd
		frappe.log_error(error_message, "IPD Submission Error")
		raise

@frappe.whitelist()
def create_process_records(doc):
	processes = []
	colour_mapping = {}
	final_colours = set()
	if isinstance(doc, string_types):
		doc = frappe._dict(json.loads(doc))
	ipd_name = doc.get('item')
	if doc.get('colour_mapping'):
		for mapping in doc.get('colour_mapping'):
			colour_mapping[mapping['from_colour']] = mapping['to_colour']
		if doc.get('colour'):
			for row in doc.get('colour'):
				if row['colour'] in colour_mapping:
					final_colours.add(colour_mapping[row['colour']])
				else:
					final_colours.add(row['colour'])
		if doc.get('processes'):
			for process in doc.get('processes'):
				is_changed = 0
				if process['process_name'] in ['Dyeing', 'Bleaching']:
					new_doc = get_new_doc(ipd_name, process)
					for row in new_doc.colour_shade_mapping:
						if row.colour in colour_mapping:
							row.colour = colour_mapping[row.colour]
							is_changed = 1
					if is_changed:
						new_doc.save()
						process['process_record'] = new_doc.name
				if process['process_name'] == 'Cutting':
					new_doc = get_new_doc(ipd_name, process)
					for row in new_doc.colour_mapping:
						if row.colour in colour_mapping:
							row.colour = colour_mapping[row.colour]
							is_changed = 1
					if is_changed:
						new_doc.save()
						process['process_record'] = new_doc.name
				if process['process_name'] in ['Stitching', 'Label Fusing', 'Packing']:
					new_doc = get_new_doc(ipd_name, process)
					if process['process_name'] == 'Stitching':
						for row in new_doc.colour_mappings:
							if row.piece_colour in colour_mapping:
								row.piece_colour = colour_mapping[row.piece_colour]
								is_changed = 1
							if row.part_colour in colour_mapping:
								row.part_colour = colour_mapping[row.part_colour]
								is_changed = 1
					if new_doc.additional_parts_colour:
						for row in new_doc.additional_parts_colour:
							if row.piece_colour in colour_mapping:
								row.piece_colour = colour_mapping[row.piece_colour]
								is_changed = 1
							if row.part_colour in colour_mapping:
								row.part_colour = colour_mapping[row.part_colour]
								is_changed = 1
							else:
								frappe.throw(
									_(f"Unable to swap the additional part colour {row.part_colour} in process record {process['process_record']} at row {process['idx']}")
								)
					if is_changed:
						new_doc.save()
						process['process_record'] = new_doc.name
				processes.append({
						'input_item': process['input_item'] if 'input_item' in process else '',
						'input_index':process['input_index'] if 'input_index' in process else '',
						'process_name': process['process_name'],
						'process_record': process['process_record'],
						'ipd_name': process['ipd_name'] if 'ipd_name' in process else '',
						'ipd_process_index': process['ipd_process_index'] if 'ipd_process_index' in process else '',
						'previous_process': process['previous_process'] if 'previous_process' in process else ''})
	return [processes, final_colours]


def get_new_doc(ipd_name, process):
	temp = 0
	doc_name = ''
	existing_doc = frappe.get_doc(process['process_name'], process['process_record'])
	new_doc = frappe.copy_doc(existing_doc)
	while True:
		temp+=1
		if not frappe.db.exists(process['process_name'], f'{ipd_name} - {temp}'):
			new_doc.name = f'{ipd_name} - {temp}'
			break
	return new_doc