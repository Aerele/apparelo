// Copyright (c) 2019, Aerele Technologies Private Limited and contributors
// For license information, please see license.txt

frappe.ui.form.on('DC', {
	refresh: function(frm) {
		if (frm.doc.docstatus === 1 && frm.doc.return_materials) {
			frm.add_custom_button(__("GRN"), ()=> {
				frm.trigger("make_grn");
			}, __('Create'));
		}
		frm.page.set_inner_btn_group_as_primary(__('Create'));
	},
	make_grn: function() {
		frappe.model.open_mapped_doc({
			method: "apparelo.apparelo.doctype.dc.dc.make_grn",
			frm: cur_frm,
			freeze_message: __("Creating GRN ...")
		})
	},
	onload: function(frm) {
		frm.set_value("company",frappe.defaults.get_default("company"));
		frappe.db.get_list("Address",{filters:{is_shipping_address: 1}}).then(data => {
			if(data && data.length){
				frm.set_value("company_address_name",data[0].name);
			}
		})
		frm.set_df_property("select_helper","options",['','Copy Over', 'Divide Total Quantity'].join('\n'))
		frm.set_df_property("from_field","options",['Available Qty','Delivery Qty','Secondary Qty'].join('\n'))
		frm.set_df_property("to_field","options",['Available Qty','Delivery Qty','Secondary Qty'].join('\n'))
		frm.set_query("supplier", function() {
			return {
				query: "apparelo.apparelo.doctype.dc.dc.get_supplier",
				filters: {
					"supplier_process.processes": frm.doc.process_1
				}
			};
		});
		frm.set_query("supplier_address_name", function() {
			return {
				filters: {
					"link_doctype": "Supplier",
					"link_name": frm.doc.supplier
				}
			}
		});
		frm.set_query("company_address_name", function() {
			return {
				filters: {
					"link_doctype": "Company",
					"link_name": frm.doc.company
				}
			}
		});
	},
	copy_over:function(frm){
		const set_fields = ['deliver_later','pf_item_code','item_code','available_quantity','quantity','primary_uom','secondary_qty','secondary_uom','delivery_location'];
		frappe.call({
			method: "apparelo.apparelo.doctype.dc.dc.duplicate_values",
			freeze: true,
			args: {doc: frm.doc},
			callback: function(r) {
				if(r.message) {
					frm.set_value('items', []);
					$.each(r.message, function(i, d) {
						var item = frm.add_child('items');
						for (let key in d) {
							if (d[key] && in_list(set_fields, key)) {
								item[key] = d[key];
							}
						}
					});
				}
				refresh_field('items');
			}
		});
	},
	attribute: function(frm)
	{
		frappe.call({
			method: "apparelo.apparelo.doctype.grn.grn.get_attribute_value",
			freeze: true,
			args: {attribute: frm.doc.attribute},
			callback: function(r) {
			  if(r.message) {
				frm.set_df_property("attribute_value","options",r.message);
			  }
			}
		  });
	},
	make_entry:function(frm){
		const set_fields = ['item_code', 'uom', 'qty', 'projected_qty', 'secondary_uom', 'additional_parameters', 'pf_item_code', 'bom'];
		frappe.call({
			method: "apparelo.apparelo.doctype.dc.dc.make_entry",
			freeze: true,
			args: {
				doc: frm.doc
			},
			callback: function(r) {
				if(r.message) {
					$.each(r.message, function(i, d) {
						var item = frm.add_child('return_materials');
						for (let key in d) {
							if (d[key] && in_list(set_fields, key)) {
								item[key] = d[key];
							}
						}
					});
				}
				refresh_field('return_materials');
			}
		});

	},
	supplier:function(frm){
		if (frm.doc.supplier)
		{
			frappe.call({
				method:"apparelo.apparelo.doctype.dc.dc.get_supplier_based_address",
				args:{supplier: frm.doc.supplier},
				callback: function(r){
					if (r.message){
						frm.set_value("supplier_address_name",r.message)
					}
					else {
						frm.set_value("supplier_address_name","")
					}
				}
			})
		}
		update_supplier_and_company_address(frm,frm.doc.supplier_address_name, "supplier_address");
		refresh_field('supplier_address_name');
	},
	location:function(frm){
		update_company_address(frm);
		update_supplier_and_company_address(frm,frm.doc.company_address_name, "company_address");
		},
	company:function(frm){
		update_company_address(frm);
		update_supplier_and_company_address(frm,frm.doc.company_address_name, "company_address");
	},
	company_address_name: function(frm) {
		update_supplier_and_company_address(frm,frm.doc.company_address_name, "company_address");
	},
	supplier_address_name: function(frm) {
		update_supplier_and_company_address(frm,frm.doc.supplier_address_name, "supplier_address");
	},
	
	get_items:function(frm) {
		const items_set_fields =['item_code','available_quantity','primary_uom','secondary_uom','pf_item_code'];
		const return_materials_set_fields = ['item_code', 'uom', 'qty', 'projected_qty', 'secondary_uom', 'additional_parameters', 'pf_item_code', 'bom'];
		frappe.call({
			method: "apparelo.apparelo.doctype.dc.dc.make_dc",
			freeze: true,
			args: {doc: frm.doc},
			callback: function(r) {
				if(r.message) {
					frm.set_value('items', []);
					$.each(r.message.items, function(i, d) {
						var item = frm.add_child('items');
						for (let key in d) {
							if (d[key] && in_list(items_set_fields, key)) {
								item[key] = d[key];
							}
						}
					});

					frm.set_value('return_materials', []);
					$.each(r.message.return_materials, function(i, d) {
						var item = frm.add_child('return_materials');
						for (let key in d) {
							if (d[key] && in_list(return_materials_set_fields, key)) {
								item[key] = d[key];
							}
						}
					});
				}
				refresh_field('items');
				refresh_field('return_materials');
			}
		});
	},
	divide_total_quantity: function(frm){
		const set_fields = ['item_code','primary_uom','quantity','available_quantity','pf_item_code',"secondary_uom"];
		frappe.call({
			method: "apparelo.apparelo.doctype.dc.dc.divide_total_quantity",
			freeze: true,
			args: {doc: frm.doc},
			callback: function(r) {
				if(r.message) {
					frm.set_value('items', []);
					$.each(r.message, function(i, d) {
						var item = frm.add_child('items');
						for (let key in d) {
							if (d[key] && in_list(set_fields, key)) {
								item[key] = d[key];
							}
						}
					});
				}
				refresh_field('items');
			}
		});	
	},
	get_return_item: function(frm) {
		const set_fields = ['item_code', 'uom', 'qty', 'projected_qty', 'secondary_uom', 'additional_parameters', 'pf_item_code', 'bom'];
		frappe.call({
			method: "apparelo.apparelo.doctype.dc.dc.calculate_expected_qty_from_delivery_qty",
			freeze: true,
			args: {
				doc: frm.doc
			},
			callback: function(r) {
				if(r.message) {
					frm.set_value('return_materials', []);
					$.each(r.message, function(i, d) {
						var item = frm.add_child('return_materials');
						for (let key in d) {
							if (d[key] && in_list(set_fields, key)) {
								item[key] = d[key];
							}
						}
					});
				}
				refresh_field('return_materials');
			}
		});

	},
	delete_unavailable_delivery_items:function(frm){
		const set_fields = ['deliver_later','pf_item_code','item_code','available_quantity','quantity','primary_uom','secondary_qty','secondary_uom','delivery_location'];
		frappe.call({
			method: "apparelo.apparelo.doctype.dc.dc.delete_unavailable_delivery_items",
			freeze: true,
			args: {doc: frm.doc},
			callback: function(r) {
				if(r.message) {
					frm.set_value('items', []);
					$.each(r.message, function(i, d) {
						var item = frm.add_child('items');
						for (let key in d) {
							if (d[key] && in_list(set_fields, key)) {
								item[key] = d[key];
							}
						}
					});
				}
				refresh_field('items');
			}
		});
	},
	delete_unavailable_return_items:function(frm){
		const set_fields = ['pf_item_code','item_code','bom','qty','projected_qty','uom','secondary_qty','secondary_uom','additional_parameters'];
		frappe.call({
			method: "apparelo.apparelo.doctype.dc.dc.delete_unavailable_return_items",
			freeze: true,
			args: {doc: frm.doc},
			callback: function(r) {
				if(r.message) {
					frm.set_value('return_materials', []);
					$.each(r.message, function(i, d) {
						var item = frm.add_child('return_materials');
						for (let key in d) {
							if (d[key] && in_list(set_fields, key)) {
								item[key] = d[key];
							}
						}
					});
				}
				refresh_field('return_materials');
			}
		});
	},
	calculate_delivery_quantity:function(frm) {
		const set_fields =['item_code', 'available_quantity', 'quantity', 'primary_uom', 'secondary_uom', 'secondary_qty', 'pf_item_code'];
		frappe.call({
			method: "apparelo.apparelo.doctype.dc.dc.get_delivery_qty_from_return_materials",
			freeze: true,
			args: {doc: frm.doc},
			callback: function(r) {
				if(r.message) {
					frm.set_value('items', []);
					$.each(r.message, function(i, d) {
						var item = frm.add_child('items');
						for (let key in d) {
							if (d[key] && in_list(set_fields, key)) {
								item[key] = d[key];
							}
						}
					});
				}
				refresh_field('items');
			}
		});
	},
});

var update_company_address = function(frm){
	if (frm.doc.location && frm.doc.company)
	{
		frappe.call({
			method:"apparelo.apparelo.doctype.dc.dc.get_location_based_address",
			args:{location:frm.doc.location, company:frm.doc.company},
			callback: function(r){
				if (r.message){
					frm.set_value("company_address_name",r.message)
				}
				else {
					frappe.db.get_list("Address",{filters:{is_shipping_address: 1}}).then(data => {
						if(data && data.length){
							frm.set_value("company_address_name",data[0].name);
						}
					})
				}
			}
		})
	}
	refresh_field('company_address_name');
}

var update_supplier_and_company_address = function(frm,address_name,address_field){
	if(address_name) {
		frappe.call({
			method: "frappe.contacts.doctype.address.address.get_address_display",
			args: {"address_dict": address_name},
			callback: function(r) {
				frm.set_value(address_field, r.message);
			}
		})
	}
	if(!address_name){
		frm.set_value(address_field, "");
	}
}