import logging
import json
import os
import time

from PyQt5 import QtWidgets
from PyQt5.QtWidgets import QWidget
from PyQt5.QtWidgets import QMainWindow
from PyQt5.QtWidgets import QMessageBox
from PyQt5.QtWidgets import QLabel
from PyQt5.QtWidgets import QComboBox
from PyQt5.QtWidgets import QCheckBox
from PyQt5.QtWidgets import QPlainTextEdit
from PyQt5.QtWidgets import QLineEdit
from PyQt5.QtCore import QSize
from PyQt5.QtCore import QPoint

NaN = float('nan')


def config_logger(name: str = __name__, level: int = logging.DEBUG):
    logger = logging.getLogger(name)
    if not logger.hasHandlers():
        logger.propagate = False
        logger.setLevel(level)
        f_str = '%(asctime)s,%(msecs)3d %(levelname)-7s %(filename)s %(funcName)s(%(lineno)s) %(message)s'
        log_formatter = logging.Formatter(f_str, datefmt='%H:%M:%S')
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(log_formatter)
        logger.addHandler(console_handler)
    return logger


def get_all_widgets(obj: QtWidgets.QWidget):
    wgts = []
    lout = obj.layout()
    for k in range(lout.count()):
        wgt = lout.itemAt(k).widget()
        if wgt is not None and isinstance(wgt, QtWidgets.QWidget) and wgt not in wgts:
            wgts.append(wgt)
        if isinstance(wgt, QtWidgets.QFrame):
            # recursive call
            wgts1 = get_all_widgets(wgt)
            for wgt1 in wgts1:
                if wgt1 not in wgts:
                    wgts.append(wgt1)
    return wgts


def checkBox_set_bg_color(cb: QCheckBox, m, colors=('green', 'red', 'white')):
    if isinstance(m, bool):
        if m:
            cb.setStyleSheet('QCheckBox::indicator { background: ' + colors[0] + ';}')
        else:
            cb.setStyleSheet('QCheckBox::indicator { background: ' + colors[1] + ';}')
    elif isinstance(m, str):
        cb.setStyleSheet('QCheckBox::indicator { background: ' + m + ';}')
    elif isinstance(m, int):
        cb.setStyleSheet('QCheckBox::indicator { background: ' + colors[m] + ';}')


def get_widget_state(obj, config, name=None):
    try:
        if name is None:
            name = obj.objectName()
        if isinstance(obj, QLineEdit):
            config[name] = str(obj.text())
        elif isinstance(obj, QComboBox):
            config[name] = {'items': [str(obj.itemText(k)) for k in range(obj.count())],
                            'index': obj.currentIndex()}
        elif isinstance(obj, QtWidgets.QAbstractButton):
            config[name] = obj.isChecked()
        elif isinstance(obj, QPlainTextEdit) or isinstance(obj, QtWidgets.QTextEdit):
            config[name] = str(obj.toPlainText())
        elif isinstance(obj, QtWidgets.QSpinBox) or isinstance(obj, QtWidgets.QDoubleSpinBox):
            config[name] = obj.value()
    except:
        return


def set_widget_state(obj, config, name=None):
    try:
        if name is None:
            name = obj.objectName()
        if name not in config:
            return
        if isinstance(obj, QLineEdit):
            obj.setText(config[name])
        elif isinstance(obj, QComboBox):
            obj.setUpdatesEnabled(False)
            bs = obj.blockSignals(True)
            obj.clear()
            obj.addItems(config[name]['items'])
            obj.blockSignals(bs)
            obj.setUpdatesEnabled(True)
            obj.setCurrentIndex(config[name]['index'])
            # Force index change event in the case of index=0
            if config[name]['index'] == 0:
                obj.currentIndexChanged.emit(0)
        elif isinstance(obj, QtWidgets.QAbstractButton):
            obj.setChecked(config[name])
        elif isinstance(obj, QPlainTextEdit) or isinstance(obj, QtWidgets.QTextEdit):
            obj.setPlainText(config[name])
        elif isinstance(obj, QtWidgets.QSpinBox) or isinstance(obj, QtWidgets.QDoubleSpinBox):
            obj.setValue(config[name])
    except:
        return


def restore_settings(self, widgets=(), file_name='config.json'):
    self.config = {}
    try:
        with open(file_name, 'r') as configfile:
            s = configfile.read()
        self.config = json.loads(s)
        # restore log level
        if 'log_level' in self.config:
            v = self.config['log_level']
            self.logger.setLevel(v)
        # restore window size and position
        if 'main_window' in self.config:
            self.resize(QSize(self.config['main_window']['size'][0], self.config['main_window']['size'][1]))
            self.move(QPoint(self.config['main_window']['position'][0], self.config['main_window']['position'][1]))
        for w in widgets:
            set_widget_state(w, self.config)
        self.logger.log(logging.INFO, 'Configuration restored from %s' % file_name)
    except:
        self.logger.log(logging.WARNING, 'Configuration restore error from %s' % file_name)
        self.logger.log(logging.DEBUG, 'Exception:', exc_info=True)
    return self.config


def save_settings(self, widgets=(), file_name='config.json'):
    try:
        # Save window size and position
        p = self.pos()
        s = self.size()
        self.config['main_window'] = {'size': (s.width(), s.height()), 'position': (p.x(), p.y())}
        for w in widgets:
            get_widget_state(w, self.config)
        with open(file_name, 'w') as configfile:
            configfile.write(json.dumps(self.config, indent=4))
        self.logger.info('Configuration saved to %s' % file_name)
        return True
    except:
        self.logger.log(logging.WARNING, 'Configuration save error to %s' % file_name)
        self.logger.log(logging.DEBUG, 'Exception:', exc_info=True)
        return False


def read_folder(folder, mask='.py'):
    # read al files in the folder
    all_files = os.listdir(folder)
    # filter files
    filtered_files = [f for f in all_files if f.endswith(mask)]
    return filtered_files


def time_ms():
    t = time.time()
    return time.strftime('%H:%M:%S') + (',%3d' % int((t - int(t)) * 1000.0))


channels = ['channel_state' + str(k) for k in range(12)]


def check_timer_state(timer_device):
    if timer_device is None:
        return False
    state = False
    avs = []
    try:
        avs = timer_device.read_attributes(channels)
    except:
        pass
    for av in avs:
        state = state or av.value
    return state
