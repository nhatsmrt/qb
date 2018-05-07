from typing import Tuple, Set, Dict, List, Callable, Iterable, Optional
import csv
import json
import re
import pickle
from collections import defaultdict
from unidecode import unidecode

from nltk.corpus import wordnet

from qanta import qlogging
from qanta.util.constants import WIKI_TITLES_PICKLE, ALL_WIKI_REDIRECTS, GUESSER_TRAIN_FOLD, BUZZER_TRAIN_FOLD
from qanta.util.io import safe_open
from qanta.ingestion.annotated_mapping import PageAssigner


log = qlogging.get(__name__)

ExpansionRule = Callable[[str], Iterable[str]]
MatchRule = Callable[[str], Optional[str]]


def mapping_rules_to_answer_map(
        expansion_rules: List[Tuple[str, ExpansionRule]],
        match_rules: List[Tuple[str, MatchRule]],
        wiki_titles: Set[str], wiki_redirects_source,
        unmapped_answers: Set[str]):
    exact_titles = {t: t for t in wiki_titles}
    unicode_titles = {unidecode(t): t for t in wiki_titles}
    lower_titles = {t.lower(): t for t in wiki_titles}
    lower_unicode_titles = {unidecode(t.lower()): t for t in wiki_titles}

    exact_wiki_redirects = {text: page for text, page in wiki_redirects_source.items()}
    unicode_wiki_redirects = {unidecode(text): page for text, page in wiki_redirects_source.items()}
    lower_wiki_redirects = {text.lower(): page for text, page in wiki_redirects_source.items()}
    lower_unicode_wiki_redirects = {unidecode(text.lower()): page for text, page in wiki_redirects_source.items()}

    answer_map = {}

    # Clone the set to prevent accidental mutation of the original
    unmapped_answers = set(unmapped_answers)

    original_num = len(unmapped_answers)
    log.info(f'{original_num} Unmapped Answers Exist\nStarting Answer Mapping\n')

    expansion_answer_map = defaultdict(set)
    for ans in unmapped_answers:
        expansion_answer_map[ans].add(ans)

    for name, rule_func in expansion_rules:
        log.info(f'Applying expansion rule: {name}')
        for raw_ans in unmapped_answers:
            for exp_ans in rule_func(raw_ans):
                expansion_answer_map[raw_ans].add(exp_ans.strip())

    for name, rule_func in match_rules:
        curr_num = len(unmapped_answers)
        log.info(f'Applying rule: {name}')

        for original_ans, ans_expansions in expansion_answer_map.items():
            for raw_ans in ans_expansions:
                rule_ans = re.sub(r'\s+', ' ', rule_func(raw_ans).strip()).strip()
                lower_ans = rule_ans.lower()

                # continue statements: We only need at least one expansion to match.
                # Once we find it we can skip looking at the others
                # Order here matters. We should go from the most strict match conditions to
                # most flexible (eg exact before lowercase, unicode ignoring before lowercase).
                m = try_match(rule_ans, exact_titles)
                if m is not None:
                    answer_map[original_ans] = m
                    continue

                m = try_match(rule_ans, exact_wiki_redirects)
                if m is not None:
                    answer_map[original_ans] = m
                    continue

                m = try_match(rule_ans, unicode_titles)
                if m is not None:
                    answer_map[original_ans] = m
                    continue

                m = try_match(rule_ans, unicode_wiki_redirects)
                if m is not None:
                    answer_map[original_ans] = m
                    continue

                m = try_match(lower_ans, lower_titles)
                if m is not None:
                    answer_map[original_ans] = m
                    continue

                m = try_match(lower_ans, lower_wiki_redirects)
                if m is not None:
                    answer_map[original_ans] = m
                    continue

                m = try_match(lower_ans, lower_unicode_titles)
                if m is not None:
                    answer_map[original_ans] = m
                    continue

                m = try_match(lower_ans, lower_unicode_wiki_redirects)
                if m is not None:
                    answer_map[original_ans] = m
                    continue

        unmapped_answers -= set(answer_map.keys())
        removed_num = curr_num - len(unmapped_answers)
        log.info(f'{removed_num} Answers Mapped')
        log.info(f'{len(unmapped_answers)} remain\n')

    end_num = len(unmapped_answers)
    log.info(f'\nAnswer Mapping Complete\n{end_num} Unmapped Remain, {len(answer_map)} Mappings Found')

    return answer_map, unmapped_answers


# Expansion rule functions
def or_rule(ans):
    splits = re.split('[^a-zA-Z]+or[^a-zA-Z]+', ans)
    if len(splits) > 1:
        formatted_splits = [s.strip() for s in splits]
        return formatted_splits
    else:
        return ()


def prompt_rule(ans):
    ans = ans.lower()
    if 'accept' in ans or 'prompt' in ans or 'pronounce' in ans:
        m = re.match(r'(.+)\(.*(?:accept|prompt|pronounce).*\)', ans)
        if m is not None:
            return (m.group(1).strip(),)

        m = re.match(r'(.+)\[.*(?:accept|prompt|pronounce).*\]', ans)
        if m is not None:
            return (m.group(1).strip(),)

        return ()
    elif 'or' in ans:
        m = re.match(r'(.+)\(.*(?:or).*\)', ans)
        if m is not None:
            return (m.group(1).strip(),)

        m = re.match(r'(.+)\[.*(?:or).*\]', ans)
        if m is not None:
            return (m.group(1).strip(),)

        return ()
    else:
        return ()


def the_rule(ans):
    l_ans = ans.lower()
    if 'the' in l_ans:
        return (l_ans.replace('the', ''),)
    else:
        return ('the ' + l_ans.lower(),)


def plural_rule(ans):
    singular = wordnet.morphy(ans)
    if singular is not None and singular != ans:
        return singular
    else:
        return ans


def apostraphe_rule(ans):
    if "’" in ans:
        return (ans.replace('’', "'"), ans.replace('’', ''))
    else:
        return ()


def answer_rule(ans):
    l_ans = ans.lower()
    if 'answers:' in l_ans:
        return (l_ans.replace('answers:', ''),)
    elif 'answer:' in l_ans:
        return (l_ans.replace('answer:', ''),)
    else:
        return ()


def optional_text_rule(ans):
    candidate = re.sub(r'\(.+?\)', '', ans)
    if candidate != ans:
        return (candidate,)
    else:
        return ()


def parens_rule(ans):
    if "(" in ans and ")" in ans:
        return (ans.replace('(', '').replace(')', ''),)
    else:
        return ()


def sir_rule(ans):
    if 'sir' in ans.lower():
        return (ans.lower().replace('sir', ''),)
    else:
        return ()


def unicode_rule(ans):
    unicode_ans = unidecode(ans)
    if ans != unicode_ans:
        return (unicode_ans,)
    else:
        return ()


# Match Rule Functions
def remove_braces(text):
    return re.sub(r'[{}]', '', text)


def remove_quotes(text):
    return re.sub(r'["“”]', '', text)


def remove_parens(text):
    return re.sub(r'[\(\)]', '', text)


def compose(*funcs):
    def composed_function(x):
        for f in funcs:
            x = f(x)
        return x

    return composed_function


def create_expansion_rules():
    # Apply this rules to generate multiple possible answers from one distinct answer
    expansion_rules = [
        ('or', or_rule),
        ('the', the_rule),
        ('prompt', prompt_rule),
        ('apostraphe', apostraphe_rule),
        ('parens', parens_rule),
        ('unicode', unicode_rule),
        ('sir', sir_rule),
        ('answer', answer_rule),
        ('optional-text', optional_text_rule)
    ]
    return expansion_rules


def create_match_rules():
    # Take an answer, format it, then check if there is an exact match
    match_rules = [
        ('exact match', lambda x: x),
        ('braces', remove_braces),
        ('quotes', remove_quotes),
        ('parens', remove_parens),
        ('braces+quotes', compose(remove_braces, remove_quotes)),
        ('braces+plural', compose(remove_braces, plural_rule)),
        ('quotes+braces+plural', compose(remove_braces, remove_quotes, plural_rule))
    ]
    return match_rules


def create_answer_map(unmapped_qanta_questions):
    expansion_rules = create_expansion_rules()
    match_rules = create_match_rules()

    log.info('Loading questions')
    raw_unmapped_answers = {q['answer'] for q in unmapped_qanta_questions}
    unmapped_lookup = defaultdict(list)
    for q in unmapped_qanta_questions:
        unmapped_lookup[q['answer']].append(q)

    log.info('Loading wikipedia titles')
    wiki_titles = read_wiki_titles()

    wiki_redirect_map = read_wiki_redirects(wiki_titles)

    log.info('Starting Answer Mapping Process')
    answer_map, unbound_answers = mapping_rules_to_answer_map(
        expansion_rules, match_rules,
        wiki_titles, wiki_redirect_map,
        raw_unmapped_answers
    )
    return answer_map, unbound_answers


def try_match(ans_text, title_map):
    und_text = ans_text.replace(' ', '_')
    if ans_text in title_map:
        return title_map[ans_text]
    elif und_text in title_map:
        return title_map[und_text]
    else:
        return None


def write_answer_map(answer_map, unbound_answers, answer_map_path, unbound_answer_path):
    with safe_open(answer_map_path, 'w') as f:
        json.dump({'answer_map': answer_map}, f)

    with safe_open(unbound_answer_path, 'w') as f:
        json.dump({'unbound_answers': list(sorted(unbound_answers))}, f)


def unmapped_to_mapped_questions(unmapped_qanta_questions, answer_map, page_assigner: PageAssigner):
    train_unmatched_questions = []
    test_unmatched_questions = []
    match_report = {}
    for q in unmapped_qanta_questions:
        answer = q['answer']
        qanta_id = int(q['qanta_id'])
        proto_id = q['proto_id']
        qdb_id = q['qdb_id']
        fold = q['fold']
        annotated_page, annotated_error = page_assigner.maybe_assign(
            answer=answer, question_text=q['text'], qdb_id=qdb_id, proto_id=proto_id
        )
        automatic_page = answer_map[answer] if answer in answer_map else None
        if (annotated_page is None) and (automatic_page is None):
            match_report[qanta_id] = {
                'result': 'none',
                'annotated_error': annotated_error,
                'automatic_error': None,
                'annotated_page': annotated_page,
                'automatic_page': automatic_page
            }
            if fold == GUESSER_TRAIN_FOLD or fold == BUZZER_TRAIN_FOLD:
                train_unmatched_questions.append(q)
            else:
                test_unmatched_questions.append(q)
        elif (annotated_page is not None) and (automatic_page is None):
            q['page'] = annotated_page
            match_report[qanta_id] = {
                'result': 'annotated',
                'annotated_error': annotated_error,
                'automatic_error': None,
                'annotated_page': annotated_page,
                'automatic_page': automatic_page
            }
        elif (annotated_page is None) and (automatic_page is not None):
            q['page'] = automatic_page
            match_report[qanta_id] = {
                'result': 'automatic',
                'annotated_error': annotated_error,
                'automatic_error': None,
                'annotated_page': annotated_page,
                'automatic_page': automatic_page
            }
        else:
            if annotated_page == automatic_page:
                q['page'] = automatic_page
                match_report[qanta_id] = {
                    'result': 'annotated+automatic',
                    'annotated_error': annotated_error,
                    'automatic_error': None,
                    'annotated_page': annotated_page,
                    'automatic_page': automatic_page
                }
            else:
                q['page'] = annotated_page
                match_report[qanta_id] = {
                    'result': 'disagree',
                    'annotated_error': annotated_error,
                    'automatic_error': None,
                    'annotated_page': annotated_page,
                    'automatic_page': automatic_page
                }

    return {
        'train_unmatched': train_unmatched_questions,
        'test_unmatched': test_unmatched_questions,
        'match_report': match_report
    }


def read_wiki_redirects(wiki_titles, redirect_csv_path=ALL_WIKI_REDIRECTS) -> Dict[str, str]:
    with open(redirect_csv_path) as f:
        redirect_lookup = {}
        n = 0
        for source, target in csv.reader(f, escapechar='\\'):
            if target in wiki_titles:
                redirect_lookup[source] = target
            else:
                n += 1

        log.info(f'{n} titles in redirect not found in wiki titles')

        return redirect_lookup


def read_wiki_titles(title_path=WIKI_TITLES_PICKLE) -> Set[str]:
    with open(title_path, 'rb') as f:
        return pickle.load(f)
