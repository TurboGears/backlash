import warnings

from backlash.tracing.reporters.sentry import SentryReporter

__all__ = ['SentryReporter']

warnings.warn(
    'backlash.trace_errors is deprecated. Please use backlash.tracing.reporters.sentry instead',
    DeprecationWarning)