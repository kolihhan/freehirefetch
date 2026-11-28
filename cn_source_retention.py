"""Preserve a previous public job-pro batch on a failed empty refresh."""
def batch_count(doc):
    if not isinstance(doc, dict) or not isinstance(doc.get("results"), list):
        return 0
    return sum(len(x.get("positions") or []) for x in doc["results"] if isinstance(x, dict))

def reconcile_jobpro(current, previous):
    if not isinstance(current, dict) or not isinstance(current.get("results"), list):
        current = {"ok": False, "results": [], "failed": [{"message": "malformed response"}]}
    jobs = batch_count(current)
    failures = len(current.get("failed") or [])
    failed = current.get("ok") is not True or failures > 0
    retained = not jobs and failed and batch_count(previous) > 0
    report = {"jobs": jobs, "failed_adapters": failures,
              "status": "FAILED" if failed and not jobs else "PARTIAL" if failed else "COMPLETE",
              "retained_previous": retained,
              "retained_jobs": batch_count(previous) if retained else 0}
    return previous if retained else current, report
