#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
#  IkaLog
#  ======
#  Copyright (C) 2015 Takeshi HASEGAWA
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
#
import sys

import cv2
import numpy as np

from ikalog.scenes.stateful_scene import StatefulScene
from ikalog.utils import *
from ikalog.utils.ikamatcher2.matcher import MultiClassIkaMatcher2 as MultiClassIkaMatcher

from ikalog.ml.classifier import ImageClassifier


class Spl2SalmonRunGameStart(StatefulScene):

    def reset(self):
        super(Spl2SalmonRunGameStart, self).reset()
        self.stage_votes = []

        self._last_event_msec = - 100 * 1000
        self._last_run_msec = - 100 * 1000

    def elect(self, context, votes):
        # Discard too old data.
        election_start = context['engine']['msec'] - self.election_period
        votes = list(filter(lambda e: election_start < e[0], votes))

        # count
        items = {}
        for vote in votes:
            if vote[1] is None:
                continue
            key = vote[1]
            items[key] = items.get(key, 0) + 1

        # return the best key
        sorted_keys = sorted(
            items.keys(), key=lambda x: items[x], reverse=True)
        sorted_keys.extend([None])  # fallback

        return sorted_keys[0]

    def _detect_stage(self, context):
        frame = context['engine']['frame']

        stage = self._c_stage.predict_frame(context['engine']['frame'])

        if stage == -1:
            stage = None

        return stage

    def _state_default(self, context):
        # pass matching in some scenes.
        session = self.find_scene_object('Spl2GameSession')
        if session is not None:
            if not (session._state.__name__ in ('_state_default')):
                return False

        session = self.find_scene_object('Spl2SalmonRunSession')
        if session is not None:
            if not (session._state.__name__ in ('_state_default')):
                return False



        frame = context['engine']['frame']
        if frame is None:
            return False

        stage = self._detect_stage(context)

        matched = stage is not None

        if matched:
            self.stage_votes = []
            self.stage_votes.append((context['engine']['msec'], stage))
            self._switch_state(self._state_tracking)
            return True

        return False

    def _state_tracking(self, context):
        frame = context['engine']['frame']

        if frame is None:
            return False

        stage = self._detect_stage(context)
        matched = stage is not None

        # 画面が続いているならそのまま
        if matched:
            self.stage_votes.append((context['engine']['msec'], stage))
            return True

        # 1000ms 以内の非マッチはチャタリングとみなす
        if not matched and self.matched_in(context, 1000):
            return False

        # それ以上マッチングしなかった場合 -> シーンを抜けている
        if not self.matched_in(context, 20000, attr='_last_event_msec'):
            context['game']['map'] = self.elect(context, self.stage_votes)

            if not context['game']['start_time']:
                # start_time should be initialized in GameGoSign.
                # This is a fallback in case GameGoSign was skipped.
                context['game']['start_time'] = IkaUtils.getTime(context)
                context['game']['start_offset_msec'] = \
                    context['engine']['msec']

            self._call_plugins('on_salmonrun_game_start', params={'stage': context['game']['map']})
            self._last_event_msec = context['engine']['msec']

        self._switch_state(self._state_default)
        return False

    def _analyze(self, context):
        pass

    def dump(self, context):
        for v in self.stage_votes:
            if v[1] is None:
                continue
            print('stage', v[0], v[1])


    def _init_scene(self, debug=False):
        self.election_period = 5 * 1000  # msec
        self._c_stage = ImageClassifier()
        self._c_stage.load_from_file('data/spl2/spl2.salmon_run.game_start.dat')


if __name__ == "__main__":
    Spl2SalmonRunGameStart.main_func()
