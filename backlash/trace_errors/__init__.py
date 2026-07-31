# HERE JUST FOR BACKWARD COMPATIBILITY
import warnings

from backlash.tracing.errors import TraceErrorsMiddleware
from backlash.tracing.reporters.mail import EmailReporter

__all__ = ['TraceErrorsMiddleware', 'EmailReporter']

warnings.warn(
    'backlash.trace_errors is deprecated. Please use backlash.tracing.errors instead',
    DeprecationWarning)