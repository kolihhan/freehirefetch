import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cn_source_retention import reconcile_jobpro
import public_quality

class CNSourceRetentionTests(unittest.TestCase):
    def setUp(self):
        self.previous={"ok":True,"results":[{"company":"bytedance","positions":[{"post_id":"123","title":"Agent Engineer","work_cities":["Beijing"]}]}],"failed":[]}

    def test_failed_empty_preserves_previous_but_reports_zero_fresh(self):
        published,report=reconcile_jobpro({"ok":False,"results":[],"failed":[{"message":"timeout"}]},self.previous)
        self.assertEqual(published,self.previous)
        self.assertEqual(report["jobs"],0)
        self.assertEqual(report["status"],"FAILED")
        self.assertEqual(report["retained_jobs"],1)
        self.assertTrue(report["retained_previous"])

    def test_malformed_response_preserves_previous(self):
        published,report=reconcile_jobpro(None,self.previous)
        self.assertEqual(published,self.previous)
        self.assertTrue(report["retained_previous"])

    def test_successful_empty_does_not_resurrect_old_roles(self):
        current={"ok":True,"results":[],"failed":[]}
        published,report=reconcile_jobpro(current,self.previous)
        self.assertEqual(published,current)
        self.assertEqual(report["status"],"COMPLETE")
        self.assertFalse(report["retained_previous"])

    def test_partial_rows_stay_current_not_mixed_with_old(self):
        current={"ok":False,"results":[{"company":"alibaba","positions":[{"post_id":"456"}]}],"failed":[{"message":"one adapter failed"}]}
        published,report=reconcile_jobpro(current,self.previous)
        self.assertEqual(published,current)
        self.assertEqual(report["status"],"PARTIAL")
        self.assertFalse(report["retained_previous"])

    def test_clean_projection_marks_retained_rows(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            p=root/"feed/cn-native"
            p.mkdir(parents=True)
            (p/"jobpro-agent.json").write_text(json.dumps(self.previous))
            (p/"health.json").write_text(json.dumps({"jobpro":{"agent":{"status":"FAILED","retained_previous":True}}}))
            with patch.object(public_quality,"official_url",return_value="https://jobs.bytedance.com/experienced/position/123/detail"):
                rows,_,_,_=public_quality.collect(root)
            matches=[x for x in rows if x["source"]=="jobpro-list"]
            self.assertEqual(len(matches),1)
            self.assertEqual(matches[0]["discovery_freshness"],"RETAINED_UNVERIFIED")
            self.assertEqual(matches[0]["source_run_status"],"FAILED")

if __name__=="__main__":
    unittest.main()
