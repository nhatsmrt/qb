#!/usr/bin/env python
# pylint: disable=wrong-import-position
import os
import json
import sys
import pickle
from typing import List


if "DISPLAY" not in os.environ:
    import matplotlib

    matplotlib.use("agg")

import glob
import click
import pandas as pd
from pandas.api.types import CategoricalDtype
import numpy as np
from scipy.stats import binned_statistic
from plotnine import (
    ggplot,
    aes,
    facet_wrap,
    ggtitle,
    labeller,
    geom_smooth,
    geom_density,
    geom_histogram,
    geom_bar,
    geom_line,
    geom_point,
    geom_errorbar,
    geom_errorbarh,
    stat_summary_bin,
    coord_flip,
    stat_smooth,
    scale_y_continuous,
    scale_x_continuous,
    xlab,
    ylab,
    theme,
    element_text,
    element_blank,
    stat_ecdf,
    ylim,
    scale_color_manual,
    scale_color_discrete,
    coord_cartesian,
)


QB_ROOT = os.environ.get("QB_ROOT", "")
DEV_REPORT_PATTERN = os.path.join(
    QB_ROOT, "output/guesser/best/**/guesser_report_guessdev.pickle"
)
TEST_REPORT_PATTERN = os.path.join(
    QB_ROOT, "output/guesser/best/**/guesser_report_guesstest.pickle"
)
EXPO_REPORT_PATTERN = os.path.join(
    QB_ROOT, "output/guesser/best/**/guesser_report_expo.pickle"
)


def eprint(*args, **kwargs):
    print(*args, file=sys.stderr, **kwargs)


@click.group()
def main():
    pass


def safe_path(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    return path


def category_jmlr(cat):
    if cat in {"Religion", "Myth", "Philosophy"}:
        return "Religion/Myth/Philosophy"
    elif cat == "Trash":
        return "Popular Culture"
    else:
        return cat


def int_to_correct(num):
    if num == 1:
        return "Correct"
    else:
        return "Wrong"


def save_plot(output_dir, guesser_name, name, plot, width=None, height=None):
    plot.save(
        safe_path(os.path.join(output_dir, guesser_name, name)),
        width=width,
        height=height,
    )


class GuesserReport:
    def __init__(self, unpickled_report, fold):
        self.fold = fold
        self.char_df = unpickled_report["char_df"]
        self.first_df = unpickled_report["first_df"]
        self.full_df = unpickled_report["full_df"]
        self.guesser_name = unpickled_report["guesser_name"]

        self.full_df["seen"] = "Full Question"
        self.first_df["seen"] = "First Sentence"
        self.combined_df = pd.concat([self.full_df, self.first_df])
        self.combined_df["Outcome"] = self.combined_df.correct.map(int_to_correct)
        self.combined_df["category_jmlr"] = self.combined_df.category.map(category_jmlr)
        self.combined_df = (
            self.combined_df.groupby(["qanta_id", "seen"]).nth(0).reset_index()
        )

        self.char_plot_df = (
            self.char_df.sort_values("score", ascending=False)
            .groupby(["qanta_id", "char_index"])
            .nth(0)
            .reset_index()
        )
        self.char_plot_df["category_jmlr"] = self.char_plot_df.category.map(
            category_jmlr
        )
        self.char_plot_df["Outcome"] = self.char_plot_df.correct.map(int_to_correct)
        self.first_accuracy = unpickled_report["first_accuracy"]
        self.full_accuracy = unpickled_report["full_accuracy"]
        self.unanswerable_answer_percent = unpickled_report[
            "unanswerable_answer_percent"
        ]
        self.unanswerable_question_percent = unpickled_report[
            "unanswerable_question_percent"
        ]

    def plot_n_train_vs_accuracy(self):
        return (
            ggplot(self.combined_df)
            + facet_wrap("seen")
            + aes(x="n_train", fill="Outcome")
            + geom_histogram(binwidth=1)
        )

    def plot_char_percent_vs_accuracy_histogram(self, category=False):
        if category:
            return (
                ggplot(self.char_plot_df)
                + facet_wrap("category_jmlr")
                + aes(x="char_percent", fill="Outcome")
                + geom_histogram(binwidth=0.05)
            )
        else:
            return (
                ggplot(self.char_plot_df)
                + aes(x="char_percent", fill="Outcome")
                + geom_histogram(binwidth=0.05)
            )

    def plot_char_percent_vs_accuracy_smooth(self, category=False):
        if category:
            return (
                ggplot(self.char_plot_df)
                + aes(x="char_percent", y="correct", color="category_jmlr")
                + geom_smooth()
            )
        else:
            return (
                ggplot(self.char_plot_df)
                + aes(x="char_percent", y="correct")
                + geom_smooth(method="mavg")
            )


GUESSER_SHORT_NAMES = {
    "qanta.guesser.rnn.RnnGuesser": " RNN",
    "qanta.guesser.dan.DanGuesser": " DAN",
    "qanta.guesser.elasticsearch.ElasticSearchGuesser": "IR",
}


def to_shortname(name):
    if name in GUESSER_SHORT_NAMES:
        return GUESSER_SHORT_NAMES[name]
    else:
        return name


def to_dataset(fold):
    if fold == "expo":
        return "Challenge Questions"
    elif fold == "guesstest":
        return "Regular Test"
    else:
        return fold


def label_source(original):
    if original == "es":
        return "Round 1 - IR Adversarial"
    elif original == "rnn":
        return "Round 2 - RNN Adversarial"
    elif original == "rnn-exact":
        return "Round 2 - Exact-RNN Adversarial"
    elif original == "rnn-noexact":
        return "Round 2 - NoExact-RNN Adversarial"
    elif original == "rnn-paired":
        return "Round 2 - Paired-RNN Adversarial"
    elif original == "rnn-nopaired":
        return "Round 2 - NoPaired-RNN Adversarial"
    elif original == "rnn-sheet":
        return "Round 2 - Sheet-RNN Adversarial"
    elif original == "rnn-nosheet":
        return "Round 2 - NoSheet-RNN Adversarial"
    elif original == "rnn-packet34":
        return "Round 2 - P34-RNN Adversarial"
    elif original == "es-2":
        return "Round 2 - IR Adversarial"
    else:
        raise ValueError(f"unknown source: {original}")


def mean_no_se(series, mult=1):
    m = np.mean(series)
    se = mult * np.sqrt(np.var(series) / len(series))
    return pd.DataFrame({"y": [m], "ymin": m, "ymax": m})


def sort_humans(humans):
    def order(h):
        if "Intermediate" in h:
            return -1
        elif "Expert" in h:
            return 0
        elif "National" in h:
            return 1

    return sorted(humans, key=order)


ENABLE_EDIT_INFO = False


class CompareGuesserReport:
    def __init__(
        self,
        reports: List[GuesserReport],
        mvg_avg_char=False,
        exclude_zero_train=False,
        merge_humans=False,
        no_humans=False,
        rounds="1,2",
        title="",
        y_max=None,
        save_df=None,
    ):
        self.save_df = save_df
        self.y_max = y_max
        self.rounds = {int(n) for n in rounds.split(",")}
        self.title = title
        self.mvg_avg_char = mvg_avg_char
        self.reports = reports
        self.exclude_zero_train = exclude_zero_train
        self.merge_humans = merge_humans
        self.no_humans = no_humans
        char_plot_dfs = []
        acc_rows = []
        for r in self.reports:
            char_plot_dfs.append(r.char_plot_df)
            name = to_shortname(r.guesser_name)
            dataset = to_dataset(r.fold)
            acc_rows.append((r.fold, name, "First Sentence", r.first_accuracy, dataset))
            acc_rows.append((r.fold, name, "Full Question", r.full_accuracy, dataset))
        self.char_plot_df = pd.concat(char_plot_dfs)
        if self.exclude_zero_train:
            self.char_plot_df = self.char_plot_df[self.char_plot_df.n_train > 0]
        self.char_plot_df["Guessing_Model"] = self.char_plot_df["guesser"].map(
            to_shortname
        )
        self.char_plot_df["Dataset"] = self.char_plot_df["fold"].map(to_dataset)
        self.char_plot_df["source"] = "unknown"
        if os.path.exists("data/external/datasets/merged_trickme-id-model.json"):
            if ENABLE_EDIT_INFO and os.path.exists("output/tacl/edit_info.json"):
                with open("output/tacl/edit_info.json") as f:
                    eprint("Using output/tacl/edit_info.json")
                    edit_info = {e["post_qanta_id"]: e for e in json.load(f)}
                    trick_to_email = None
            elif os.path.exists("output/tacl/tacl-spreadsheet.tsv"):
                with open("data/external/datasets/qanta.tacl-trick.json") as f:
                    trick_to_qanta_id = {
                        q["trick_id"]: q["qanta_id"]
                        for q in json.load(f)["questions"]
                        if q["trick_id"] is not None
                    }
                eprint("Using output/tacl/tacl-spreadsheet.tsv")
                sheet_df = pd.read_csv(
                    "output/tacl/tacl-spreadsheet.tsv",
                    header=0,
                    sep="\t",
                    index_col=None,
                )
                sheet_df = sheet_df.rename(
                    columns={"ID": "trick_id", "Author (by e-mail)": "email"}
                )
                sheet_df = sheet_df[["trick_id", "email"]]
                trick_to_email = {}
                for t in sheet_df.itertuples():
                    if t.trick_id not in trick_to_qanta_id:
                        raise ValueError(f"Trick id not in qanta id map: {t.trick_id}")
                    trick_to_email[trick_to_qanta_id[t.trick_id]] = t.email
                edit_info = None
            else:
                edit_info = None
                trick_to_email = None
            eprint("Separating questions into rnn/es")
            with open("data/external/datasets/merged_trickme-id-model.json") as f:
                trick_sources = json.load(f)
                id_rows = []
                for sqid, source in trick_sources.items():
                    sqid = int(sqid)
                    if edit_info is not None:
                        # Only update rnn source for debugging
                        if source == "rnn":
                            if sqid in edit_info:
                                if edit_info[sqid]["exact"]:
                                    source = "rnn-exact"
                                else:
                                    source = "rnn-noexact"
                            else:
                                raise ValueError(f"No edit info for: {sqid}")
                    elif trick_to_email is not None:
                        if sqid in trick_to_email:
                            if trick_to_email[sqid] in (
                                "kurtisPacket3@gmail.com",
                                "kurtisPacket4@gmail.com",
                            ):
                                source = "rnn-packet34"
                    id_rows.append({"qanta_id": sqid, "source": source, "fold": "expo"})
                id_df = pd.DataFrame(id_rows)
                self.char_plot_df = self.char_plot_df.merge(
                    id_df, on=("qanta_id", "fold"), how="left"
                )
                self.char_plot_df["source"] = self.char_plot_df["source_y"].fillna(
                    "unknown"
                )
                if trick_to_email is not None:
                    eprint(
                        f"N Questions pre filter: {len(self.char_plot_df.qanta_id.unique())}"
                    )
                    self.char_plot_df = self.char_plot_df[
                        self.char_plot_df["source"] != "rnn-packet34"
                    ]
                    eprint(
                        f"N Questions post filter: {len(self.char_plot_df.qanta_id.unique())}"
                    )
                self.char_plot_df.loc[
                    self.char_plot_df.source != "unknown", "Dataset"
                ] = self.char_plot_df[self.char_plot_df.source != "unknown"][
                    "source"
                ].map(
                    label_source
                )
        self.acc_df = pd.DataFrame.from_records(
            acc_rows, columns=["fold", "guesser", "position", "accuracy", "Dataset"]
        )

    def plot_char_percent_vs_accuracy_smooth(
        self, expo=False, no_models=False, columns=False
    ):
        if self.y_max is not None:
            limits = [0, float(self.y_max)]
            eprint(f"Setting limits to: {limits}")
        else:
            limits = [0, 1]
        if expo:
            if (
                os.path.exists("data/external/all_human_gameplay.json")
                and not self.no_humans
            ):
                with open("data/external/all_human_gameplay.json") as f:
                    all_gameplay = json.load(f)
                    frames = []
                    for event, name in [
                        ("parents", "Intermediate"),
                        ("maryland", "Expert"),
                        ("live", "National"),
                    ]:
                        if self.merge_humans:
                            name = "Human"
                        gameplay = all_gameplay[event]
                        if event != "live":
                            control_correct_positions = gameplay[
                                "control_correct_positions"
                            ]
                            control_wrong_positions = gameplay[
                                "control_wrong_positions"
                            ]
                            control_positions = (
                                control_correct_positions + control_wrong_positions
                            )
                            control_positions = np.array(control_positions)
                            control_result = np.array(
                                len(control_correct_positions) * [1]
                                + len(control_wrong_positions) * [0]
                            )
                            argsort_control = np.argsort(control_positions)
                            control_x = control_positions[argsort_control]
                            control_sorted_result = control_result[argsort_control]
                            control_y = (
                                control_sorted_result.cumsum()
                                / control_sorted_result.shape[0]
                            )
                            control_df = pd.DataFrame(
                                {"correct": control_y, "char_percent": control_x}
                            )
                            control_df["Dataset"] = "Regular Test"
                            control_df["Guessing_Model"] = f" {name}"
                            frames.append(control_df)

                        adv_correct_positions = gameplay["adv_correct_positions"]
                        adv_wrong_positions = gameplay["adv_wrong_positions"]
                        adv_positions = adv_correct_positions + adv_wrong_positions
                        adv_positions = np.array(adv_positions)
                        adv_result = np.array(
                            len(adv_correct_positions) * [1]
                            + len(adv_wrong_positions) * [0]
                        )
                        argsort_adv = np.argsort(adv_positions)
                        adv_x = adv_positions[argsort_adv]
                        adv_sorted_result = adv_result[argsort_adv]
                        adv_y = adv_sorted_result.cumsum() / adv_sorted_result.shape[0]
                        adv_df = pd.DataFrame({"correct": adv_y, "char_percent": adv_x})
                        adv_df["Dataset"] = "IR Adversarial"
                        adv_df["Guessing_Model"] = f" {name}"
                        frames.append(adv_df)

                        if len(gameplay["advneural_correct_positions"]) > 0:
                            adv_correct_positions = gameplay[
                                "advneural_correct_positions"
                            ]
                            adv_wrong_positions = gameplay["advneural_wrong_positions"]
                            adv_positions = adv_correct_positions + adv_wrong_positions
                            adv_positions = np.array(adv_positions)
                            adv_result = np.array(
                                len(adv_correct_positions) * [1]
                                + len(adv_wrong_positions) * [0]
                            )
                            argsort_adv = np.argsort(adv_positions)
                            adv_x = adv_positions[argsort_adv]
                            adv_sorted_result = adv_result[argsort_adv]
                            adv_y = (
                                adv_sorted_result.cumsum() / adv_sorted_result.shape[0]
                            )
                            adv_df = pd.DataFrame(
                                {"correct": adv_y, "char_percent": adv_x}
                            )
                            adv_df["Dataset"] = "RNN Adversarial"
                            adv_df["Guessing_Model"] = f" {name}"
                            frames.append(adv_df)

                    human_df = pd.concat(frames)
                    human_vals = sort_humans(list(human_df["Guessing_Model"].unique()))
                    human_dtype = CategoricalDtype(human_vals, ordered=True)
                    human_df["Guessing_Model"] = human_df["Guessing_Model"].astype(
                        human_dtype
                    )
                    dataset_dtype = CategoricalDtype(
                        ["Regular Test", "IR Adversarial", "RNN Adversarial"],
                        ordered=True,
                    )
                    human_df["Dataset"] = human_df["Dataset"].astype(dataset_dtype)

            if no_models:
                p = ggplot(human_df) + geom_point(shape=".")
            else:
                df = self.char_plot_df
                if 1 not in self.rounds:
                    df = df[df["Dataset"] != "Round 1 - IR Adversarial"]
                if 2 not in self.rounds:
                    df = df[df["Dataset"] != "Round 2 - IR Adversarial"]
                    df = df[df["Dataset"] != "Round 2 - RNN Adversarial"]
                p = ggplot(df)
                if self.save_df is not None:
                    eprint(f"Saving df to: {self.save_df}")
                    df.to_json(self.save_df)

                if (
                    os.path.exists("data/external/all_human_gameplay.json")
                    and not self.no_humans
                ):
                    eprint("Loading human data")
                    p = p + geom_line(data=human_df)

            if columns:
                facet_conf = facet_wrap("Guessing_Model", ncol=1)
            else:
                facet_conf = facet_wrap("Guessing_Model", nrow=1)

            if not no_models:
                if self.mvg_avg_char:
                    chart = stat_smooth(
                        method="mavg", se=False, method_args={"window": 400}
                    )
                else:
                    chart = stat_summary_bin(
                        fun_data=mean_no_se,
                        bins=20,
                        shape=".",
                        linetype="None",
                        size=0.5,
                    )
            else:
                chart = None

            p = p + facet_conf + aes(x="char_percent", y="correct", color="Dataset")
            if chart is not None:
                p += chart
            p = (
                p
                + scale_y_continuous(breaks=np.linspace(0, 1, 6))
                + scale_x_continuous(breaks=[0, 0.5, 1])
                + coord_cartesian(ylim=limits)
                + xlab("Percent of Question Revealed")
                + ylab("Accuracy")
                + theme(
                    # legend_position='top', legend_box_margin=0, legend_title=element_blank(),
                    strip_text_x=element_text(margin={"t": 6, "b": 6, "l": 1, "r": 5})
                )
                + scale_color_manual(
                    values=["#FF3333", "#66CC00", "#3333FF", "#FFFF33"],
                    name="Questions",
                )
            )
            if self.title != "":
                p += ggtitle(self.title)

            return p
        else:
            if self.save_df is not None:
                eprint(f"Saving df to: {self.save_df}")
                df.to_json(self.save_df)
            return (
                ggplot(self.char_plot_df)
                + aes(x="char_percent", y="correct", color="Guessing_Model")
                + stat_smooth(method="mavg", se=False, method_args={"window": 500})
                + scale_y_continuous(breaks=np.linspace(0, 1, 6))
                + coord_cartesian(ylim=limits)
            )

    def plot_compare_accuracy(self, expo=False):
        if expo:
            return (
                ggplot(self.acc_df)
                + facet_wrap("position")
                + aes(x="guesser", y="accuracy", fill="Dataset")
                + geom_bar(stat="identity", position="dodge")
                + xlab("Guessing Model")
                + ylab("Accuracy")
            )
        else:
            return (
                ggplot(self.acc_df)
                + facet_wrap("position")
                + aes(x="guesser", y="accuracy")
                + geom_bar(stat="identity")
            )


def save_all_plots(output_dir, report: GuesserReport, expo=False):
    if not expo:
        save_plot(
            output_dir,
            report.guesser_name,
            "n_train_vs_accuracy.pdf",
            report.plot_n_train_vs_accuracy(),
        )
    save_plot(
        output_dir,
        report.guesser_name,
        "char_percent_vs_accuracy_histogram.pdf",
        report.plot_char_percent_vs_accuracy_histogram(category=False),
    )

    if not expo:
        save_plot(
            output_dir,
            report.guesser_name,
            "char_percent_vs_accuracy_histogram_category.pdf",
            report.plot_char_percent_vs_accuracy_histogram(category=True),
        )
    save_plot(
        output_dir,
        report.guesser_name,
        "char_percent_vs_accuracy_smooth.pdf",
        report.plot_char_percent_vs_accuracy_smooth(category=False),
    )

    if not expo:
        save_plot(
            output_dir,
            report.guesser_name,
            "char_percent_vs_accuracy_smooth_category.pdf",
            report.plot_char_percent_vs_accuracy_smooth(category=True),
        )


@main.command()
@click.option("--use-test", is_flag=True, default=False)
@click.option("--only-tacl", is_flag=True, default=False)
@click.option("--no-models", is_flag=True, default=False)
@click.option("--no-humans", is_flag=True, default=False)
@click.option("--columns", is_flag=True, default=False)
@click.option("--no-expo", is_flag=True, default=False)
@click.option("--mvg-avg-char", is_flag=True, default=False)
@click.option("--exclude-zero-train", is_flag=True, default=False)
@click.option("--merge-humans", is_flag=True, default=False)
@click.option("--rounds", default="1,2")
@click.option("--title", default="")
@click.option("--y-max", default=None)
@click.option("--save-df", default=None, type=str)
@click.argument("output_dir")
def guesser(
    use_test,
    only_tacl,
    no_models,
    no_humans,
    columns,
    no_expo,
    mvg_avg_char,
    exclude_zero_train,
    merge_humans,
    rounds,
    title,
    y_max,
    save_df,
    output_dir,
):
    if use_test:
        REPORT_PATTERN = TEST_REPORT_PATTERN
        report_fold = "guesstest"
    else:
        REPORT_PATTERN = DEV_REPORT_PATTERN
        report_fold = "guessdev"
    dev_reports = []
    for path in glob.glob(REPORT_PATTERN):
        if only_tacl and "VWGuesser" in path:
            continue
        with open(path, "rb") as f:
            report = GuesserReport(pickle.load(f), report_fold)
            dev_reports.append(report)

        if not only_tacl:
            save_all_plots(output_dir, report)

    if not no_expo:
        expo_reports = []
        expo_output_dir = safe_path(os.path.join(output_dir, "expo"))
        for path in glob.glob(EXPO_REPORT_PATTERN):
            if only_tacl and "VWGuesser" in path:
                continue
            with open(path, "rb") as f:
                report = GuesserReport(pickle.load(f), "expo")
                expo_reports.append(report)

            if not only_tacl:
                save_all_plots(expo_output_dir, report, expo=True)

    if not only_tacl:
        compare_report = CompareGuesserReport(dev_reports, rounds=rounds, title=title)
        save_plot(
            output_dir,
            "compare",
            "position_accuracy.pdf",
            compare_report.plot_compare_accuracy(),
        )
        save_plot(
            output_dir,
            "compare",
            "char_accuracy.pdf",
            compare_report.plot_char_percent_vs_accuracy_smooth(),
        )

    eprint(f"N Expo Reports {len(expo_reports)}")
    if not no_expo and (len(expo_reports) > 0 or no_models):
        compare_report = CompareGuesserReport(
            dev_reports + expo_reports,
            mvg_avg_char=mvg_avg_char,
            exclude_zero_train=exclude_zero_train,
            merge_humans=merge_humans,
            no_humans=no_humans,
            rounds=rounds,
            title=title,
            y_max=y_max,
            save_df=save_df,
        )
        save_plot(
            output_dir,
            "compare",
            "expo_position_accuracy.pdf",
            compare_report.plot_compare_accuracy(expo=True),
        )
        if columns:
            height = 6.0
            width = 1.7
        else:
            height = 1.7
            width = 7.0
        save_plot(
            output_dir,
            "compare",
            "expo_char_accuracy.pdf",
            compare_report.plot_char_percent_vs_accuracy_smooth(
                expo=True, no_models=no_models, columns=columns
            ),
            height=height,
            width=width,
        )


if __name__ == "__main__":
    main()
