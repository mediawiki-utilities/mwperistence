r"""
``$ mwpersistence persistence2stats -h``
::

    Generates revision-level statistics from a sequence of token persistence
    infused revision documents into revision statistics.

    Usage:
        persistence2stats (-h | --help)
        persistence2stats [<input-file>...] [--min-persisted=<num>]
                          [--min-visible=<hours>] [--include=<regex>]
                          [--exclude=<regex>] [--keep-tokens] [--threads=<num>]
                          [--output=<path>] [--compress=<type>] [--verbose]
                          [--debug]

    Options:
        -h --help               Print this documentation
        <input-file>            The path to a file containing persistence data.
                                [default: <stdin>]
        --min-persisted=<revs>  The minimum number of revisions a token must
                                survive before being considered "persisted"
                                [default: 5]
        --min-visible=<hours>   The minimum amount of time a token must survive
                                before being considered "persisted" (in hours)
                                [default: 10]
        --include=<regex>       A regex matching tokens to include (case
                                insensitive) [default: <all>]
        --exclude=<regex>       A regex matching tokens to exclude (case
                                insensitive) [default: <none>]
        --keep-tokens           Do not drop 'tokens' field data from the JSON
                                document.
        --threads=<num>         If a collection of files are provided, how many
                                processor threads should be prepare?
                                [default: <cpu_count>]
        --output=<path>         Write output to a directory with one output
                                file per input path.  [default: <stdout>]
        --compress=<type>       If set, output written to the output-dir will
                                be compressed in this format. [default: bz2]
        --verbose               Print out progress information
        --debug                 Print debug logging to stderr.
"""
import logging
import re
import sys
from math import log

import mwcli
import mwxml.utilities

logger = logging.getLogger(__name__)


def process_args(args):

    if args['--include'] == "<all>":
        include = None
    else:
        include_re = re.compile(args['--include'], re.UNICODE | re.I)
        include = lambda t: bool(include_re.search(t))

    if args['--exclude'] == "<none>":
        exclude = None
    else:
        exclude_re = re.compile(args['--exclude'], re.UNICODE | re.I)
        exclude = lambda t: bool(exclude_re.search(t))

    return {'min_persisted': int(args['--min-persisted']),
            'min_visible': float(args['--min-visible']) * (60 * 60),
            'keep_tokens': bool(args['--keep-tokens']),
            'include': include,
            'exclude': exclude}


def _persistence2stats(*args, keep_tokens, **kwargs):
    docs = persistence2stats(*args, **kwargs)
    if not keep_tokens:
        docs = drop_tokens(docs)

    yield from docs


def drop_tokens(rev_docs):
    for rev_doc in rev_docs:
        rev_doc['persistence'].pop('tokens', None)
        yield rev_doc


def persistence2stats(rev_docs, min_persisted=5, min_visible=1209600,
                      include=None, exclude=None, verbose=False):
    """
    Processes a sorted and page-partitioned sequence of revision documents into
    and adds statistics to the 'persistence' field each token "added" in the
    revision persisted through future revisions.

    :Parameters:
        rev_docs : `iterable` ( `dict` )
            JSON documents of revision data containing a 'diff' field as
            generated by ``dump2diffs``.  It's assumed that rev_docs are
            partitioned by page and otherwise in chronological order.
        window_size : `int`
            The size of the window of revisions from which persistence data
            will be generated.
        min_persisted : `int`
            The minimum future revisions that a token must persist in order
            to be considered "persistent".
        min_visible : `int`
            The minimum number of seconds that a token must be visible in order
            to be considered "persistent".
        include : `func`
            A function that returns `True` when a token should be included in
            statistical processing
        exclude : `str` | `re.SRE_Pattern`
            A function that returns `True` when a token should *not* be
            included in statistical processing (Takes precedence over
            'include')
        verbose : `bool`
            Prints out dots and stuff to stderr

    :Returns:
        A generator of rev_docs with a 'persistence' field containing
        statistics about individual tokens.
    """
    rev_docs = mwxml.utilities.normalize(rev_docs)

    min_persisted = int(min_persisted)
    min_visible = int(min_visible)
    include = include if include is not None else lambda t: True
    exclude = exclude if exclude is not None else lambda t: False

    for rev_doc in rev_docs:
        persistence_doc = rev_doc['persistence']
        stats_doc = {
            'tokens_added': 0,
            'persistent_tokens': 0,
            'non_self_persistent_tokens': 0,
            'sum_log_persisted': 0,
            'sum_log_non_self_persisted': 0,
            'sum_log_seconds_visible': 0,
            'censored': False,
            'non_self_censored': False
        }

        filtered_docs = (t for t in persistence_doc['tokens']
                         if include(t['text']) and not exclude(t['text']))
        for token_doc in filtered_docs:
            if verbose:
                sys.stderr.write(".")
                sys.stderr.flush()

            stats_doc['tokens_added'] += 1
            stats_doc['sum_log_persisted'] += log(token_doc['persisted'] + 1)
            stats_doc['sum_log_non_self_persisted'] += \
                log(token_doc['non_self_persisted'] + 1)
            stats_doc['sum_log_seconds_visible'] += \
                log(token_doc['seconds_visible'] + 1)

            # Look for time threshold
            if token_doc['seconds_visible'] >= min_visible:
                stats_doc['persistent_tokens'] += 1
                stats_doc['non_self_persistent_tokens'] += 1
            else:
                # Look for review threshold
                stats_doc['persistent_tokens'] += \
                    token_doc['persisted'] >= min_persisted

                stats_doc['non_self_persistent_tokens'] += \
                    token_doc['non_self_persisted'] >= min_persisted

                # Check for censoring
                if persistence_doc['seconds_possible'] < min_visible:
                    stats_doc['censored'] = True
                    stats_doc['non_self_censored'] = True

                else:
                    if persistence_doc['revisions_processed'] < min_persisted:
                        stats_doc['censored'] = True

                    if persistence_doc['non_self_processed'] < min_persisted:
                        stats_doc['non_self_censored'] = True

        if verbose:
            sys.stderr.write("\n")
            sys.stderr.flush()

        rev_doc['persistence'].update(stats_doc)

        yield rev_doc


streamer = mwcli.Streamer(
    __doc__,
    __name__,
    _persistence2stats,
    process_args
)
main = streamer.main
