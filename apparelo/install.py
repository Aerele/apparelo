from __future__ import print_function, unicode_literals

import frappe
from frappe import _
from frappe.desk.page.setup_wizard.setup_wizard import add_all_roles_to
from frappe.custom.doctype.custom_field.custom_field import create_custom_field
from apparelo.apparelo.doctype.knitting import knitting
from apparelo.apparelo.doctype.dyeing import dyeing
from apparelo.apparelo.doctype.bleaching import bleaching
from apparelo.apparelo.doctype.compacting import compacting
from apparelo.apparelo.doctype.steaming import steaming
from apparelo.apparelo.doctype.cutting import cutting


def after_install():
    create_item_attributes()
    create_item_template()

def create_item_attributes():
    knitting.create_item_attribute()
    dyeing.create_item_attribute()
    cutting.create_item_attribute()

def create_item_template():
    knitting.create_item_template()
    dyeing.create_item_template()
    bleaching.create_item_template()
    compacting.create_item_template()
    steaming.create_item_template()