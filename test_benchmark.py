from unittest import TestCase

from benchmark import LAYOUTS, run


class BenchmarkTests(TestCase):
    def test_layouts_preserve_results(self):
        layouts = run(10_000, 10, 42)["layouts"]
        self.assertEqual(set(layouts), set(LAYOUTS))
        for query in layouts["baseline"]["queries"]:
            self.assertEqual(len({item["queries"][query]["result_sha256"] for item in layouts.values()}), 1)
        self.assertGreater(layouts["covering"]["file_bytes"], layouts["baseline"]["file_bytes"])

    def test_well_matched_covering_index_is_used(self):
        result = run(10_000, 10, 42)
        plan = result["layouts"]["covering"]["queries"]["hot_tenant"]["plan"]
        self.assertTrue(any("COVERING INDEX event_covering" in step for step in plan), plan)
