#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import configparser
import json
import os
import sys
from functools import partial
from subprocess import Popen, PIPE
from time import sleep
from types import SimpleNamespace
from queue import Queue

from PySide2.QtCore import QCoreApplication, QFile, QObject, Signal, QThread
from PySide2.QtUiTools import QUiLoader
from PySide2.QtWidgets import (QAction, QApplication, QCheckBox, QColorDialog,
                               QLabel, QLineEdit, QPushButton, QSpinBox,
                               QTextEdit)
import zmq

cfg = configparser.ConfigParser()
cfg.read(os.path.join(os.path.dirname(__file__), 'messenger.ini'))

_config = SimpleNamespace(
    color=cfg.get('PREVIEW', 'color'),
    clip=cfg.get('PREVIEW', 'clip'),
    width=cfg.get('PREVIEW', 'width'),
    height=cfg.get('PREVIEW', 'height')
)


# Inherit from QThread
class Worker(QObject):
    std_error = Signal(str)

    def __init__(self, queue):
        QObject.__init__(self)
        self.is_running = True
        self._proc = None
        self._queue = queue

        if _config.clip:
            self.input = ['-i', _config.clip]
        else:
            self.input = ['-f', 'lavfi', 'color=s={}x{}:c={}'.format(
                _config.width, _config.height, _config.color)]

    def work(self):
        while self.is_running:
            if self._queue.get():
                cmd = ['ffplay', '-hide_banner', '-nostats'] + self.input + [
                    '-vf', "scale='{}:{}',zmq,drawtext=text=''".format(
                        _config.width, _config.height)]
                self._proc = Popen(cmd, stderr=PIPE)

                for line in self._proc.stderr:
                    print(line.decode())

                self._queue.put(False)
                print("done...")

    def quit(self):
        self.is_running = False


class MainForm(QObject):
    """
    Main Window Form
    this class draws the program window
    """

    def __init__(self, parent=None):
        super(MainForm, self).__init__(parent)
        self.root_path = os.path.dirname(__file__)
        ui_file = QFile(os.path.join(self.root_path, 'messenger.ui'))
        ui_file.open(QFile.ReadOnly)

        loader = QUiLoader()
        self.window = loader.load(ui_file)
        ui_file.close()

        action_quit = self.window.findChild(QAction, 'action_quit')
        action_quit.triggered.connect(self.quit_application)
        action_save = self.window.findChild(QAction, 'action_save')
        action_save.triggered.connect(self.save_preset)

        # form content
        self.text = self.window.findChild(QTextEdit, 'text_area')
        self.pos_x = self.window.findChild(QLineEdit, 'text_x_pos')
        self.pos_y = self.window.findChild(QLineEdit, 'text_y_pos')

        self.font_color = self.window.findChild(QPushButton,
                                                'botton_font_color')
        self.font_color_preview = self.window.findChild(QLabel,
                                                        'label_font_color')
        self.font_color.setStyleSheet("background-color: #fff;")

        self.font_color_t = self.window.findChild(QLineEdit, 'text_font_color')
        self.font_color_t.setText('#ffffff')
        self.font_size = self.window.findChild(QSpinBox, 'spin_font_size')
        self.alpha = self.window.findChild(QLineEdit, 'text_alpha')

        self.show_box = self.window.findChild(QCheckBox, 'activate_box')
        self.box_color = self.window.findChild(QPushButton, 'botton_box_color')
        self.box_color.setStyleSheet("background-color: #000;")
        self.box_color_t = self.window.findChild(QLineEdit, 'text_box_color')
        self.box_color_t.setText('#000000')
        self.border_w = self.window.findChild(QSpinBox, 'spin_border_width')

        self.font_color.clicked.connect(partial(self.change_color,
                                                self.font_color,
                                                self.font_color_t))
        self.box_color.clicked.connect(partial(self.change_color,
                                               self.box_color,
                                               self.box_color_t))

        self.save = self.window.findChild(QPushButton, 'button_save')
        self.save.clicked.connect(self.save_preset)

        self.play = self.window.findChild(QPushButton, 'button_preview')
        self.play.clicked.connect(self.preview_text)

        # preview worker
        self.filter_queue = Queue()
        self.worker = Worker(self.filter_queue)
        self.worker_thread = QThread()
        self.worker_thread.started.connect(self.worker.work)
        self.worker.moveToThread(self.worker_thread)

        # zmq sender
        self.context = zmq.Context()
        self.port = "5555"

        # load default text preset
        with open(os.path.join(self.root_path, 'presets',
                               'default.json')) as f:
            self.set_content(json.load(f))

        self.window.installEventFilter(self)
        self.window.show()
        self.setParent(self.window)

    def change_color(self, btn, text):
        color = QColorDialog.getColor(initial='#ffffff', parent=None,
                                      title='Select Color',
                                      options=QColorDialog.ShowAlphaChannel)

        if color.isValid():
            btn.setStyleSheet(
                "background-color: {}".format(color.name()))
            text.setText('{}@0x{:02x}'.format(color.name(), color.alpha()))

    def set_content(self, preset):
        self.text.insertPlainText(preset['text'])
        self.pos_x.setText(preset['x'])
        self.pos_y.setText(preset['y'])
        self.font_color.setStyleSheet(
            "background-color: {}; border: 0px;".format(
                preset['fontcolor'].split('@')[0]))
        self.font_color_t.setText(preset['fontcolor'])
        self.font_size.setValue(preset['fontsize'])
        self.alpha.setText(preset['alpha'])
        self.show_box.setChecked(preset['box'])
        self.box_color.setStyleSheet(
            "background-color: {}; border: 0px;".format(
                preset['boxcolor'].split('@')[0]))
        self.box_color_t.setText(preset['boxcolor'])
        self.border_w.setValue(preset['boxborderw'])

    def get_content(self):
        content = {
            'text': self.text.toPlainText(),
            'x': self.pos_x.text(),
            'y': self.pos_y.text(),
            'fontcolor': self.font_color_t.text(),
            'fontsize': self.font_size.value(),
            'alpha': self.alpha.text(),
            'box': 1 if self.show_box.isChecked() else 0,
            'boxcolor': self.box_color_t.text(),
            'boxborderw': self.border_w.value()
        }

        return content

    def preview_text(self):
        filter_str = ''
        if not self.worker_thread.isRunning():
            self.worker_thread.start()

        self.filter_queue.put(True)

        sleep(1)

        socket = self.context.socket(zmq.REQ)
        socket.connect("tcp://localhost:{}".format(self.port))

        for key, value in self.get_content().items():
            filter_str += '{}={}:'.format(key, value)

        _filter = filter_str.replace(' ', '\\ ').rstrip(':')
        print(_filter)
        socket.send_string("Parsed_drawtext_2 reinit " + _filter)

        message = socket.recv()
        print("Received reply: ", message.decode())

    def save_preset(self):
        print(self.get_content())

    def quit_application(self):
        QCoreApplication.quit()


def main():
    app = QApplication(sys.argv)
    main_window = MainForm()
    app.aboutToQuit.connect(main_window.quit_application)
    sys.exit(app.exec_())


if __name__ == '__main__':
    main()
