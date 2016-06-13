# Evaluate DroidBot with androcov
# basic idea is:
# A tool is better if it has higher coverage
__author__ = 'yuanchun'

import argparse
import os
import logging
import sys
import threading
import time
import subprocess
import re
import json
from datetime import datetime

from droidbot.droidbot import DroidBot


class CoverageEvaluator(object):
    """
    evaluate test tool with DroidBox
    make sure you have started droidbox emulator before evaluating
    """
    MODE_DEFAULT = "1.default"
    MODE_MONKEY = "2.monkey"
    MODE_RANDOM = "3.random"
    MODE_STATIC = "4.static"
    MODE_DYNAMIC = "5.dynamic"

    def __init__(self, device_serial, apk_path,
                 event_duration, event_count, event_interval,
                 output_dir, androcov_path):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.device_serial = device_serial,
        self.apk_path = os.path.abspath(apk_path)
        self.output_dir = output_dir
        self.androcov_path = androcov_path

        self.modes = {
            CoverageEvaluator.MODE_DEFAULT: "none",
            CoverageEvaluator.MODE_MONKEY: "monkey",
            CoverageEvaluator.MODE_RANDOM: "random",
            CoverageEvaluator.MODE_STATIC: "static",
            CoverageEvaluator.MODE_DYNAMIC: "dynamic"
        }

        if self.output_dir is None:
            self.output_dir = "evaluation_reports/"
        self.output_dir = os.path.abspath(self.output_dir)
        if not os.path.exists(self.output_dir):
            os.mkdir(self.output_dir)
        self.temp_dir = os.path.join(self.output_dir, "temp")
        if os.path.exists(self.temp_dir):
            os.rmdir(self.temp_dir)
        os.mkdir(self.temp_dir)

        self.output_dirs = {}
        for mode in self.modes.keys():
            self.output_dirs[mode] = os.path.join(self.output_dir, mode)

        self.androcov_instrument()

        now = datetime.now()
        self.report_title = now.strftime("Evaluation_Report_%Y-%m-%d_%H%M")
        result_file_name = self.report_title + ".md"
        self.result_file_path = os.path.join(output_dir, result_file_name)

        self.event_duration = event_duration
        if self.event_duration is None:
            self.event_duration = 200
        self.event_count = event_count
        if self.event_count is None:
            self.event_count = 200
        self.event_interval = event_interval
        if self.event_interval is None:
            self.event_interval = 2

        self.record_interval = self.event_duration / 20
        if self.record_interval < 2:
            self.record_interval = 2

        self.droidbot = None

        self.result = {}

        self.logger.info("Evaluator initialized")
        self.logger.info("apk_path:%s\n"
                         "duration:%d\ncount:%d\ninteval:%d\nreport title:%s" %
                         (self.apk_path, self.event_duration,
                          self.event_count, self.event_interval, self.report_title))

        self.enabled = True

    def start_evaluate(self):
        """
        start droidbox testing
        :return:
        """
        if not self.enabled:
            return
        self.evaluate_mode(CoverageEvaluator.MODE_DEFAULT,
                           self.default_mode)
        self.evaluate_mode(CoverageEvaluator.MODE_MONKEY,
                           self.adb_monkey)
        self.evaluate_mode(CoverageEvaluator.MODE_RANDOM,
                           self.droidbot_random)
        self.evaluate_mode(CoverageEvaluator.MODE_STATIC,
                           self.droidbot_static)
        self.evaluate_mode(CoverageEvaluator.MODE_DYNAMIC,
                           self.droidbot_dynamic)
        self.dump(sys.stdout)
        result_file = open(self.result_file_path, "w")
        self.dump(result_file)
        result_file.close()

    def androcov_instrument(self):
        """
        instrument the app with androcov
        @return:
        """
        androcov_output_dir = self.temp_dir
        subprocess.check_call(["java", "-jar", self.androcov_path, "-i", self.apk_path, "-o", androcov_output_dir])
        result_json_file = open(os.path.join(androcov_output_dir, "instrumentation.json"))
        result_json = json.load(result_json_file)
        self.apk_path = result_json['outputAPK']
        self.all_methods = result_json['allMethods']

    def evaluate_mode(self, mode, target):
        """
        evaluate a particular mode
        :param mode: str of mode
        :param target: the target function to run
        :return:
        """
        if not self.enabled:
            return
        self.logger.info("evaluating [%s] mode" % mode)
        self.droidbot = None
        target_thread = threading.Thread(target=target)
        target_thread.start()
        self.monitor_and_record(mode)
        self.stop_modules()
        self.logger.info("finished evaluating [%s] mode" % mode)

    def stop_modules(self):
        if self.droidbot is not None:
            self.droidbot.stop()

    def monitor_and_record(self, mode):
        if not self.enabled:
            return
        self.result[mode] = {}
        t = 0
        self.logger.info("start monitoring")
        try:
            while True:
                time.sleep(self.record_interval)
                t += self.record_interval
                if t > self.event_duration:
                    return
        except KeyboardInterrupt:
            self.stop()
        self.logger.info("stop monitoring")
        self.logger.debug(self.result)

    def stop(self):
        self.enabled = False

    def start_droidbot(self, env_policy, event_policy, output_dir):
        """
        start droidbot with given arguments
        :param env_policy: policy to deploy environment
        :param event_policy: policy to send events
        :return:
        """
        if not self.enabled:
            return
        self.logger.info("starting droidbot")
        self.droidbot = DroidBot(device_serial=self.device_serial,
                                 app_path=self.apk_path,
                                 env_policy=env_policy,
                                 event_policy=event_policy,
                                 event_count=self.event_count,
                                 event_duration=self.event_duration,
                                 event_interval=self.event_interval,
                                 output_dir=output_dir,
                                 quiet=True)
        self.droidbot.start()

    def default_mode(self):
        self.start_droidbot(env_policy="none",
                            event_policy="none",
                            output_dir=self.output_dirs[CoverageEvaluator.MODE_DEFAULT])

    def adb_monkey(self):
        """
        try droidbot "monkey" mode
        :return:
        """
        self.start_droidbot(env_policy="none",
                            event_policy="monkey",
                            output_dir=self.output_dirs[CoverageEvaluator.MODE_MONKEY])

    def droidbot_random(self):
        """
        try droidbot "random" mode
        :return:
        """
        self.start_droidbot(env_policy="none",
                            event_policy="random",
                            output_dir=self.output_dirs[CoverageEvaluator.MODE_RANDOM])

    def droidbot_static(self):
        """
        try droidbot "static" mode
        :return:
        """
        self.start_droidbot(env_policy="none",
                            event_policy="static",
                            output_dir=self.output_dirs[CoverageEvaluator.MODE_STATIC])

    def droidbot_dynamic(self):
        """
        try droidbot "dynamic" mode
        :return:
        """
        self.start_droidbot(env_policy="none",
                            event_policy="dynamic",
                            output_dir=self.output_dirs[CoverageEvaluator.MODE_DYNAMIC])

    def result_safe_get(self, mode_tag=None, time_tag=None, item_tag=None):
        """
        get an item from result
        """
        if mode_tag is None:
            return self.result
        if mode_tag in self.result.keys() and isinstance(self.result[mode_tag], dict):
            result_mode = self.result[mode_tag]
            if time_tag is None:
                return result_mode
            if time_tag in result_mode.keys() and isinstance(result_mode[time_tag], dict):
                result_item = result_mode[time_tag]
                if item_tag is None:
                    return result_item
                if item_tag in result_item.keys():
                    return result_item[item_tag]
        return None

    def dump(self, out_file):
        modes = self.result_safe_get()
        if modes is None or not modes:
            return
        else:
            modes = list(modes.keys())
            modes.sort()

        out_file.write("# %s\n\n" % self.report_title)

        out_file.write("## About\n\n")
        out_file.write("This report is generated automatically by %s "
                       "with options:\n\n"
                       "+ apk_path=%s\n"
                       "+ event_duration=%s\n"
                       "+ event_interval=%s\n"
                       "+ event_count=%s\n\n"
                       % (self.__class__.__name__, os.path.basename(self.apk_path),
                          self.event_duration, self.event_interval, self.event_count))

        out_file.write("## Apk Info\n\n")
        out_file.write("|Item|Value|\n")
        out_file.write("|----|----|\n")
        out_file.write("|Package Name|%s|\n" % self.droidbox.application.getPackage())
        out_file.write("|Main Activity|%s|\n" % self.droidbox.application.getMainActivity())
        out_file.write("|Hash (md5)|%s|\n" % self.droidbox.apk_hashes[0])
        out_file.write("|Hash (sha1)|%s|\n" % self.droidbox.apk_hashes[1])
        out_file.write("|Hash (sha256)|%s|\n\n" % self.droidbox.apk_hashes[2])

        out_file.write("### Permissions\n\n")
        for permission in self.droidbox.application.getPermissions():
            out_file.write("+ %s\n" % permission)

        out_file.write("\n## Data\n\n")
        out_file.write("### Summary\n\n")
        # gen head lines
        th1 = "|\tcategory\t|"
        th2 = "|----|"
        for mode in modes:
            th1 += "\t%s\t|" % mode
            th2 += "----|"
        th1 += "\n"
        th2 += "\n"
        out_file.write(th1)
        out_file.write(th2)

        # gen content
        categories = self.result_safe_get(modes[0], 0)
        if categories is None:
            categories = []
        else:
            categories = list(categories.keys())
            categories.sort()

        for category in categories:
            tl = "|\t%s\t|" % category
            for mode in modes:
                time_tags = self.result_safe_get(mode)
                if time_tags is None:
                    tl += "\t0\t|"
                    continue
                time_tag = max(time_tags.keys())
                count = self.result_safe_get(mode, time_tag, category)
                tl += "\t%d\t|" % count
            tl += "\n"
            out_file.write(tl)

        out_file.write("\n### Tendency\n\n")
        # gen head lines
        th1 = "|\ttime\t|"
        th2 = "|----|"
        for mode in modes:
            th1 += "\t%s\t|" % mode
            th2 += "----|"
        th1 += "\n"
        th2 += "\n"
        out_file.write(th1)
        out_file.write(th2)

        # gen content
        time_tags = self.result_safe_get(modes[0])
        if time_tags is None:
            time_tags = []
        else:
            time_tags = list(time_tags.keys())
            time_tags.sort()

        for time_tag in time_tags:
            tl = "|\t%d\t|" % time_tag
            for mode in modes:
                tl += "\t%s\t|" % self.result_safe_get(mode, time_tag, "sum")
            tl += "\n"
            out_file.write(tl)


def parse_args():
    """
    parse command line input
    generate options including host name, port number
    """
    description = "Run different testing bots on droidbox, and compare their log counts."
    parser = argparse.ArgumentParser(description=description,
                                     formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("-d", action="store", dest="device_serial",
                        help="serial number of target device")
    parser.add_argument("-a", action="store", dest="apk_path", required=True,
                        help="file path of target app, necessary for static analysis")
    parser.add_argument("-count", action="store", dest="event_count",
                        type=int, help="number of events to generate during testing")
    parser.add_argument("-interval", action="store", dest="event_interval",
                        type=int, help="interval between two events (seconds)")
    parser.add_argument("-duration", action="store", dest="event_duration",
                        type=int, help="duration of droidbot running (seconds)")
    parser.add_argument("-o", action="store", dest="output_dir",
                        help="directory of output")
    parser.add_argument("-androcov", action="store", dest="androcov_path",
                        help="path to androcov.jar")
    options = parser.parse_args()
    # print options
    return options


if __name__ == "__main__":
    opts = parse_args()
    logging.basicConfig(level=logging.INFO)
    evaluator = CoverageEvaluator(
        device_serial=opts.device_serial,
        apk_path=opts.apk_path,
        event_duration=opts.event_duration,
        event_count=opts.event_count,
        event_interval=opts.event_interval,
        output_dir=opts.output_dir,
        androcov_path=opts.androcov_path
    )
    try:
        evaluator.start_evaluate()
    except KeyboardInterrupt:
        evaluator.stop()
        evaluator.dump(sys.stdout)
