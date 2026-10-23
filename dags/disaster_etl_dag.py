"""Global Disaster Intelligence ETL.

  [nasa_eonet] [gdacs] [usgs] [geonet] [reliefweb_api] [phivolcs_html]
     extract -> transform_validate -> load      <- one TaskGroup per source, run in parallel;
                     |                             invalid rows branch off to data_quarantine;
                     |                             a failed source does not block the others
          deduplicate_cross_source  (trigger_rule=all_done)
                     |
             data_quality_checks  (branch)
               /              \\
       quality_passed     quality_failed
               \\              /
             record_pipeline_status (trigger_rule=all_done, always runs)

Demo config: {"simulate_failure": ["usgs"]} = source outage,
             {"simulate_quality_failure": true} = take the quality_failed branch.
"""
from datetime import datetime, timedelta
import logging

from airflow import DAG
from airflow.decorators import task
from airflow.exceptions import AirflowFailException, AirflowSkipException
from airflow.models.param import Param
from airflow.utils.state import TaskInstanceState
from airflow.utils.task_group import TaskGroup
from airflow.utils.trigger_rule import TriggerRule

from src import pipeline
from src.database import postgres
from src.extractors.gdacs_api import GdacsOutsideVisitWindow
from src.extractors.reliefweb_api import ReliefWebAppnameMissing

log = logging.getLogger(__name__)
SOURCES = list(pipeline.EXTRACTORS)
SKIP_REASONS = {
    "reliefweb_api": "RELIEFWEB_APPNAME not configured",
    "gdacs": "outside gdacs.org robots.txt visit window 04:00-06:45 UTC",
}
# GDACS requests are 60 s apart (robots.txt), so it needs a longer timeout.
EXTRACT_TIMEOUT = {"gdacs": timedelta(minutes=15)}

with DAG(
    dag_id="global_disaster_etl",
    description="5 APIs + PHIVOLCS web scraping -> validate -> UPSERT -> dedup -> quality branch -> PostgreSQL",
    start_date=datetime(2026, 1, 1),
    # 04:30 UTC: inside the visit window requested by gdacs.org/robots.txt (04:00-06:45 UTC).
    schedule="30 4 * * *",
    catchup=False,
    max_active_runs=1,
    default_args={
        "owner": "disaster-team",
        "retries": 2,
        "retry_delay": timedelta(minutes=1),
        "retry_exponential_backoff": True,
        "execution_timeout": timedelta(minutes=5),
    },
    params={
        "simulate_failure": Param([], type="array",
                                  description=f"Sources to fail on purpose: {SOURCES}"),
        "simulate_quality_failure": Param(False, type="boolean",
                                          description="Force the quality_failed branch (demo)"),
    },
    tags=["disaster", "etl"],
) as dag:

    for source in SOURCES:
        with TaskGroup(group_id=source):

            @task(task_id="extract", execution_timeout=EXTRACT_TIMEOUT.get(source, timedelta(minutes=5)))
            def extract_task(src=source, params=None, run_id=None):
                simulate = params.get("simulate_failure") or []
                if src in simulate:
                    # Fail immediately without retries so the demo is quick.
                    raise AirflowFailException(f"Simulated outage for source '{src}'")
                try:
                    result = pipeline.extract(src, run_id)
                except (ReliefWebAppnameMissing, GdacsOutsideVisitWindow) as exc:
                    raise AirflowSkipException(str(exc)) from exc
                log.info("Extracted %s rows from %s", result["extracted"], src)
                return result

            @task(task_id="transform_validate")
            def transform_task(extract_result, run_id=None):
                result = pipeline.transform_validate(extract_result, run_id)
                log.info("Validation for %s: %s", result["source"],
                         {k: result[k] for k in ("extracted", "valid", "quarantined", "duplicates_in_batch")})
                return result

            @task(task_id="load")
            def load_task(transform_result, run_id=None):
                result = pipeline.load(transform_result, run_id)
                log.info("Loaded %s: inserted=%s updated=%s", result["source"],
                         result["inserted"], result["updated"])
                return result

            load_task(transform_task(extract_task()))

    @task(trigger_rule=TriggerRule.ALL_DONE)
    def deduplicate_cross_source():
        flagged = postgres.mark_cross_source_duplicates()
        log.info("Cross-source duplicates flagged: %s", flagged)
        return flagged

    @task.branch
    def data_quality_checks(run_id=None, params=None, ti=None):
        """Run the checks and branch: quality_passed or quality_failed."""
        results = postgres.run_quality_checks(run_id)
        for r in results:
            log.info("%-32s %s observed=%s expected %s", r["check_name"],
                     "PASS" if r["passed"] else "FAIL", r["observed_value"], r["expectation"])
        failed = [r["check_name"] for r in results if not r["passed"]]
        if params.get("simulate_quality_failure"):
            failed.append("simulated_quality_failure")
        ti.xcom_push(key="failed_checks", value=failed)
        return "quality_failed" if failed else "quality_passed"

    @task
    def quality_passed():
        log.info("All data quality checks passed; data is published to the dashboard.")

    @task
    def quality_failed(ti=None):
        failed = ti.xcom_pull(task_ids="data_quality_checks", key="failed_checks")
        # Failing checks are stored in data_quality_results and shown on the dashboard;
        # the pipeline status is recorded as 'quality_failed' by record_pipeline_status.
        log.warning("Data quality checks FAILED: %s", failed)
        return failed

    @task(trigger_rule=TriggerRule.ALL_DONE)
    def record_pipeline_status(dag_run=None, run_id=None, ti=None):
        entries, any_failed = [], False
        for source in SOURCES:
            states = {t.task_id.split(".")[-1]: t for t in dag_run.get_task_instances()
                      if t.task_id.startswith(f"{source}.")}
            load_ti = states.get("load")
            ok = load_ti is not None and load_ti.state == TaskInstanceState.SUCCESS
            extract_ti = states.get("extract")
            skipped = extract_ti is not None and extract_ti.state == TaskInstanceState.SKIPPED
            failed_step = next((name for name in ("extract", "transform_validate", "load")
                                if states.get(name) and states[name].state != TaskInstanceState.SUCCESS), None)
            stats = ti.xcom_pull(task_ids=f"{source}.load") if ok else None
            any_failed |= not ok and not skipped
            entries.append({
                "dag_id": dag_run.dag_id, "dag_run_id": run_id, "source_name": source,
                "status": "success" if ok else "skipped" if skipped else "failed",
                "records_extracted": (stats or {}).get("extracted", 0),
                "records_loaded": (stats or {}).get("loaded", 0),
                "records_quarantined": (stats or {}).get("quarantined", 0),
                "message": (f"inserted={stats['inserted']} updated={stats['updated']}" if ok
                            else f"skipped: {SKIP_REASONS.get(source, 'not run')}" if skipped
                            else f"failed at {failed_step} ({states[failed_step].state})" if failed_step
                            else "did not run"),
                "started_at": dag_run.start_date,
            })
        passed_ti = dag_run.get_task_instance("quality_passed")
        quality_ok = passed_ti is not None and passed_ti.state == TaskInstanceState.SUCCESS
        if not any(e["status"] == "success" for e in entries):
            overall = "failed"
        elif not quality_ok:
            overall = "quality_failed"
        elif any_failed:
            overall = "partial_success"
        else:
            overall = "success"
        entries.append({
            "dag_id": dag_run.dag_id, "dag_run_id": run_id, "source_name": "__overall__",
            "status": overall,
            "records_extracted": sum(e["records_extracted"] for e in entries),
            "records_loaded": sum(e["records_loaded"] for e in entries),
            "records_quarantined": sum(e["records_quarantined"] for e in entries),
            "message": f"quality_checks={'passed' if quality_ok else 'failed'}",
            "started_at": dag_run.start_date,
        })
        postgres.record_pipeline_runs(entries)
        log.info("Pipeline status: %s", overall)
        if overall == "failed":
            # Nothing could be loaded at all. A single failed source only marks its own
            # task red; the run itself carries on and succeeds with the remaining sources.
            raise AirflowFailException("No source could be loaded")
        return overall

    loads = [dag.get_task(f"{s}.load") for s in SOURCES]
    dedup = deduplicate_cross_source()
    branch = data_quality_checks()
    status = record_pipeline_status()
    loads >> dedup >> branch >> [quality_passed(), quality_failed()] >> status
