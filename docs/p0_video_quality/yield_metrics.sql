-- P0-Q yield baseline: read-only queries over facts Mac Core ALREADY persists.
-- Every value is derived from production_jobs / production_tasks / production_attempts;
-- nothing is estimated. Technical outcomes only: a Succeeded task is NOT a visually usable shot.
-- Timestamps are ISO-8601 UTC text, so julianday() differences are valid.

-- M1  technical first-pass rate per job (Succeeded with exactly one attempt)
--     named: tasks_first_pass / tasks_succeeded
-- M2  render attempts per succeeded task
-- M3  attempt wall seconds (executor-reserved attempt start to finish): an UPPER BOUND of GPU
--     occupancy, it includes ComfyUI queue wait; real GPU minutes need ComfyUI history timestamps
--     which are not persisted today.
-- M4  seconds from job creation to the first succeeded shot (first technical preview)
-- M5  seconds from job creation to the production package (all shots committed)
-- M7  tasks the plan could never execute (NeedsHuman at compile time): wasted Creative work
--
-- :job is the production_job_id.
SELECT
    j.production_job_id                                              AS production_job_id,
    j.status                                                         AS job_status,
    COUNT(t.production_task_id)                                      AS tasks_total,
    SUM(CASE WHEN t.status = 'Succeeded' THEN 1 ELSE 0 END)          AS tasks_succeeded,
    SUM(CASE WHEN t.status = 'Succeeded' AND t.attempt_count = 1
             THEN 1 ELSE 0 END)                                      AS tasks_first_pass,
    SUM(CASE WHEN t.status = 'Succeeded' THEN t.attempt_count
             ELSE 0 END)                                             AS attempts_on_succeeded_tasks,
    SUM(CASE WHEN t.execution_disposition <> 'Executable'
             THEN 1 ELSE 0 END)                                      AS tasks_not_executable,
    (SELECT ROUND(SUM((julianday(a.finished_at) - julianday(a.started_at)) * 86400.0), 1)
       FROM production_attempts a
      WHERE a.production_job_id = j.production_job_id
        AND a.finished_at IS NOT NULL)                               AS attempt_wall_seconds_finished,
    (SELECT COUNT(*) FROM production_attempts a
      WHERE a.production_job_id = j.production_job_id
        AND a.finished_at IS NULL)                                   AS attempts_unfinished,
    (SELECT ROUND((julianday(MIN(t2.finished_at)) - julianday(j.created_at)) * 86400.0, 1)
       FROM production_tasks t2
      WHERE t2.production_job_id = j.production_job_id
        AND t2.status = 'Succeeded')                                 AS seconds_to_first_shot,
    (SELECT ROUND((julianday(p.created_at) - julianday(j.created_at)) * 86400.0, 1)
       FROM production_packages p
      WHERE p.production_job_id = j.production_job_id)               AS seconds_to_package
FROM production_jobs j
LEFT JOIN production_tasks t ON t.production_job_id = j.production_job_id
WHERE j.production_job_id = :job
GROUP BY j.production_job_id;

-- M6  failure-code distribution (technical failures only)
-- :job as above.
SELECT a.failure_code AS failure_code, COUNT(*) AS attempts
  FROM production_attempts a
 WHERE a.production_job_id = :job AND a.failure_code IS NOT NULL
 GROUP BY a.failure_code
 ORDER BY attempts DESC, failure_code;
