"""Local cancellation for visual planning, independent of provider task support."""
from __future__ import annotations
import asyncio
import functools
import threading
from datetime import datetime, timezone
import httpx

_lock = threading.RLock()
_local = threading.local()
_active = {}


class AnalysisStopped(BaseException):
    """Deliberately bypass schema/transport fallback handlers."""
    def __init__(self, plan):
        self.plan = plan


class Run:
    def __init__(self, storage, plan_id, join_id, attempt_id):
        self.storage, self.plan_id, self.join_id, self.attempt_id = storage, plan_id, join_id, attempt_id
        self.abort = None
        self.stopped = False

    def check(self):
        from verified_assembly import NS
        current = self.storage.get_document(NS, self.plan_id)
        join = next(j for j in current['joins'] if j['id'] == self.join_id)
        attempt = join.get('analysisAttempt') or {}
        if self.stopped or attempt.get('id') != self.attempt_id or attempt.get('status') != 'running':
            raise AnalysisStopped(current)

    def stop(self):
        self.stopped = True
        if self.abort:
            self.abort()


def cancellable(fn):
    @functools.wraps(fn)
    def wrapped(*args, **kwargs):
        prior = getattr(_local, 'run', None)
        _local.run = None
        try:
            return fn(*args, **kwargs)
        except AnalysisStopped as stopped:
            return stopped.plan
        finally:
            run = getattr(_local, 'run', None)
            if run:
                with _lock:
                    _active.pop(run.attempt_id, None)
            _local.run = prior
    return wrapped


def bind(storage, plan, join):
    run = Run(storage, plan['id'], join['id'], join['analysisAttempt']['id'])
    _local.run = run
    with _lock:
        run.check()
        _active[run.attempt_id] = run


def save(storage, plan):
    from verified_assembly import save as original_save
    with _lock:
        run = getattr(_local, 'run', None)
        if run:
            run.check()
        return original_save(storage, plan)


def cancel(storage, body):
    from verified_assembly import load, join_for, save as original_save, fail
    attempt_id = str(body.get('analysis_attempt_id') or '').strip()
    if not attempt_id:
        fail('缺少要终止的分析编号')
    with _lock:
        plan = load(storage, body)
        join = join_for(plan, body)
        attempt = join.get('analysisAttempt') or {}
        if attempt.get('id') != attempt_id:
            fail('分析请求已经变化，请刷新后终止当前请求', 409)
        if attempt.get('status') == 'cancelled':
            return plan
        if attempt.get('status') not in ('running', 'unknown'):
            fail('这次分析已结束，无需终止', 409)
        attempt.update(status='cancelled', stage='cancelled', finishedAt=datetime.now(timezone.utc).isoformat(),
                       stoppedStage=attempt.get('stage'), localWaitStopped=True,
                       providerOutcome='unknown', providerCancellation='unconfirmed')
        plan = original_save(storage, plan)
        run = _active.get(attempt_id)
        if run:
            run.stop()
        return plan


def request(method, endpoint, *, body, headers, timeout, trust_env):
    run = getattr(_local, 'run', None)
    if not run:
        with httpx.Client(timeout=httpx.Timeout(timeout, connect=15), trust_env=trust_env) as client:
            return client.request(method, endpoint, json=body, headers=headers)
    with _lock:
        run.check()

    async def send():
        loop = asyncio.get_running_loop()
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=15), trust_env=trust_env) as client:
            task = asyncio.create_task(client.request(method, endpoint, json=body, headers=headers))
            def abort():
                if not loop.is_closed():
                    try:
                        loop.call_soon_threadsafe(task.cancel)
                    except RuntimeError:
                        pass
            with _lock:
                run.abort = abort
                if run.stopped:
                    abort()
            try:
                return await asyncio.wait_for(task, timeout=timeout)
            except asyncio.TimeoutError as exc:
                raise httpx.ReadTimeout('analysis wall-clock deadline exceeded') from exc
            except asyncio.CancelledError:
                with _lock:
                    run.check()
                raise
            finally:
                with _lock:
                    run.abort = None
    response = asyncio.run(send())
    with _lock:
        run.check()
    return response
