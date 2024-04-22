## Apparelo (deprecated)

Frappe application to manage the manufacturing workflows in the garment industry.

Reach us out at hello@aerele.in to connect with our team.

#### License

GNU/General Public License (v3) (see [license.txt](license.txt))

The Apparelo code is licensed as GNU General Public License (v3) and the copyright is owned by Aerele Technologies Pvt Ltd (Aerele) and Contributors.

#### Requirements
- [Frappe](https://frappe.io/docs).
- Note ***apparelo*** supports only python3.6 or above.

#### Installation
Navigate to your bench folder.
```
cd frappe-bench
```
Create new site and install ERPNext
```
bench new-site [site-name]
bench get-app erpnext https://github.com/frappe/erpnext.git
bench --site [site-name] install-app erpnext
```

- After installing erpnext, complete the setup wizard (need to be done before installing apparelo, as apparelo requires the entries made at the time of setup) and do the following

Install Apparelo App
```
bench get-app apparelo https://github.com/aerele/apparelo.git
bench --site [site-name] install-app apparelo
```
