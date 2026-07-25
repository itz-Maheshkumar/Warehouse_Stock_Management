from django.template.loader import render_to_string
from django.test import SimpleTestCase


class WarehouseTemplateTests(SimpleTestCase):
    def test_warehouse_list_template_renders_without_template_errors(self):
        rendered = render_to_string('warehouses/list.html', {'warehouses': []})

        self.assertIn('Warehouses', rendered)
        self.assertIn('CatParts India', rendered)

    def test_dashboard_sidebar_has_collapsible_submenu(self):
        rendered = render_to_string('components/sidebar.html')

        self.assertIn('id="dashboardSubmenu"', rendered)
        self.assertIn('data-bs-target="#dashboardSubmenu"', rendered)
