from backlash.tracing.reporters.sentry import SentryReporter

import warnings
warnings.warn(
    'backlash.trace_errors is deprecated. Please use backlash.tracing.reporters.sentry instead',
    DeprecationWarning)