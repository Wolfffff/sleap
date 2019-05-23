from PySide2 import QtCore
from PySide2.QtCore import Qt

from PySide2.QtGui import QKeyEvent

from PySide2.QtWidgets import QApplication, QMainWindow, QWidget, QDockWidget
from PySide2.QtWidgets import QVBoxLayout, QHBoxLayout, QGroupBox, QFormLayout
from PySide2.QtWidgets import QLabel, QPushButton, QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QCheckBox
from PySide2.QtWidgets import QTableWidget, QTableView, QTableWidgetItem, QAbstractItemView
from PySide2.QtWidgets import QTreeView, QTreeWidget, QTreeWidgetItem
from PySide2.QtWidgets import QMenu, QAction
from PySide2.QtWidgets import QFileDialog, QMessageBox

import os

import numpy as np
import pandas as pd

from typing import Callable

from sleap.gui.video import QtVideoPlayer, QtInstance, QtEdge, QtNode
from sleap.io.video import Video, HDF5Video, MediaVideo
from sleap.io.dataset import Labels, load_labels_json_old
from sleap.instance import LabeledFrame
from sleap.skeleton import Skeleton, Node


class VideosTable(QTableView):
    """Table view widget backed by a custom data model for displaying
    lists of Video instances. """
    def __init__(self, videos: list = []):
        super(VideosTable, self).__init__()
        self.setModel(VideosTableModel(videos))
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.SingleSelection)

class VideosTableModel(QtCore.QAbstractTableModel):
    _props = ["filename", "frames", "height", "width", "channels",]

    def __init__(self, videos: list):
        super(VideosTableModel, self).__init__()
        self._videos = videos

    @property
    def videos(self):
        return self._videos

    @videos.setter
    def videos(self, val):
        self.beginResetModel()
        self._videos = val
        self.endResetModel()

    def data(self, index: QtCore.QModelIndex, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and index.isValid():
            idx = index.row()
            prop = self._props[index.column()]

            if len(self.videos) > (idx - 1):
                video = self.videos[idx]

                if prop == "filename":
                    return os.path.basename(video.filename) # just show the name, not full path
                elif prop == "frames":
                    return video.frames
                elif prop == "height":
                    return video.height
                elif prop == "width":
                    return video.width
                elif prop == "channels":
                    return video.channels

        return None

    def rowCount(self, parent):
        return len(self.videos)

    def columnCount(self, parent):
        return len(VideosTableModel._props)

    def headerData(self, section, orientation: QtCore.Qt.Orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole:
            if orientation == QtCore.Qt.Horizontal:
                return self._props[section]
            elif orientation == QtCore.Qt.Vertical:
                return section

        return None

    def flags(self, index: QtCore.QModelIndex):
        return Qt.ItemIsEnabled | Qt.ItemIsSelectable


class SkeletonNodesTable(QTableView):
    """Table view widget backed by a custom data model for displaying and
    editing Skeleton nodes. """
    def __init__(self, skeleton: Skeleton):
        super(SkeletonNodesTable, self).__init__()
        self.setModel(SkeletonNodesTableModel(skeleton))
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.SingleSelection)

class SkeletonNodesTableModel(QtCore.QAbstractTableModel):
    _props = ["name", "symmetry"]

    def __init__(self, skeleton: Skeleton):
        super(SkeletonNodesTableModel, self).__init__()
        self._skeleton = skeleton

    @property
    def skeleton(self):
        return self._skeleton

    @skeleton.setter
    def skeleton(self, val):
        self.beginResetModel()
        self._skeleton = val
        self.endResetModel()

    def data(self, index: QtCore.QModelIndex, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and index.isValid():
            node_idx = index.row()
            prop = self._props[index.column()]
            node = self.skeleton.nodes[node_idx] # FIXME? can we assume order is stable?
            node_name = node.name

            if prop == "name":
                return node_name
            elif prop == "symmetry":
                return self.skeleton.get_symmetry_name(node_name)

        return None

    def rowCount(self, parent):
        return len(self.skeleton.nodes)

    def columnCount(self, parent):
        return len(SkeletonNodesTableModel._props)

    def headerData(self, section, orientation: QtCore.Qt.Orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole:
            if orientation == QtCore.Qt.Horizontal:
                return self._props[section]
            elif orientation == QtCore.Qt.Vertical:
                return section

        return None

    def setData(self, index: QtCore.QModelIndex, value: str, role=Qt.EditRole):
        if role == Qt.EditRole:
            node_idx = index.row()
            prop = self._props[index.column()]
            node_name = self.skeleton.nodes[node_idx].name
            try:
                if prop == "name":
                    if len(value) > 0:
                        self._skeleton.relabel_node(node_name, value)
                    # else:
                        # self._skeleton.delete_node(node_name)
                elif prop == "symmetry":
                    if len(value) > 0:
                        self._skeleton.add_symmetry(node_name, value)
                    else:
                        self._skeleton.delete_symmetry(node_name, self._skeleton.get_symmetry(node_name))

                # send signal that data has changed
                self.dataChanged.emit(index, index)

                return True
            except:
                # TODO: display feedback on error?
                pass

        return False

    def flags(self, index: QtCore.QModelIndex):
        return Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsEditable


class SkeletonEdgesTable(QTableView):
    """Table view widget backed by a custom data model for displaying and
    editing Skeleton edges. """
    def __init__(self, skeleton: Skeleton):
        super(SkeletonEdgesTable, self).__init__()
        self.setModel(SkeletonEdgesTableModel(skeleton))
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.SingleSelection)

class SkeletonEdgesTableModel(QtCore.QAbstractTableModel):
    _props = ["source", "destination"]

    def __init__(self, skeleton: Skeleton):
        super(SkeletonEdgesTableModel, self).__init__()
        self._skeleton = skeleton

    @property
    def skeleton(self):
        return self._skeleton

    @skeleton.setter
    def skeleton(self, val):
        self.beginResetModel()
        self._skeleton = val
        self.endResetModel()

    def data(self, index: QtCore.QModelIndex, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and index.isValid():
            idx = index.row()
            prop = self._props[index.column()]
            edge = self.skeleton.edges[idx]

            if prop == "source":
                return edge[0].name
            elif prop == "destination":
                return edge[1].name

        return None

    def rowCount(self, parent):
        return len(self.skeleton.edges)

    def columnCount(self, parent):
        return len(SkeletonNodesTableModel._props)

    def headerData(self, section, orientation: QtCore.Qt.Orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole:
            if orientation == QtCore.Qt.Horizontal:
                return self._props[section]
            elif orientation == QtCore.Qt.Vertical:
                return section

        return None

    def flags(self, index: QtCore.QModelIndex):
        return Qt.ItemIsEnabled | Qt.ItemIsSelectable




class LabeledFrameTable(QTableView):
    """Table view widget backed by a custom data model for displaying
    lists of Video instances. """
    def __init__(self, labeled_frame: LabeledFrame = None):
        super(LabeledFrameTable, self).__init__()
        self.setModel(LabeledFrameTableModel(labeled_frame))
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.SingleSelection)

class LabeledFrameTableModel(QtCore.QAbstractTableModel):
    _props = ["points", "track_id", "skeleton",]

    def __init__(self, labeled_frame: LabeledFrame):
        super(LabeledFrameTableModel, self).__init__()
        self._labeled_frame = labeled_frame

    @property
    def labeled_frame(self):
        return self._labeled_frame

    @labeled_frame.setter
    def labeled_frame(self, val):
        self.beginResetModel()
        self._labeled_frame = val
        self.endResetModel()

    def data(self, index: QtCore.QModelIndex, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and index.isValid():
            idx = index.row()
            prop = self._props[index.column()]

            if len(self.labeled_frame.instances) > (idx - 1):
                instance = self.labeled_frame.instances[idx]

                if prop == "points":
                    return f"{len(instance.nodes)}/{len(instance.skeleton.nodes)}"
                elif prop == "track_id":
                    return None
                elif prop == "skeleton":
                    return instance.skeleton.name

        return None

    def rowCount(self, parent):
        return len(self.labeled_frame.instances) if self.labeled_frame is not None else 0

    def columnCount(self, parent):
        return len(LabeledFrameTableModel._props)

    def headerData(self, section, orientation: QtCore.Qt.Orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole:
            if orientation == QtCore.Qt.Horizontal:
                return self._props[section]
            elif orientation == QtCore.Qt.Vertical:
                return section

        return None

    def flags(self, index: QtCore.QModelIndex):
        return Qt.ItemIsEnabled | Qt.ItemIsSelectable


class SkeletonNodeModel(QtCore.QStringListModel):

    def __init__(self, skeleton: Skeleton, src_node: Callable = None):
        super(SkeletonNodeModel, self).__init__()
        self._src_node = src_node
        self.skeleton = skeleton

    @property
    def skeleton(self):
        return self._skeleton

    @skeleton.setter
    def skeleton(self, val):
        self.beginResetModel()

        self._skeleton = val
        # if this is a dst node, then determine list based on source node
        if self._src_node is not None:
            self._node_list = self._valid_dst()
        # otherwise, show all nodes for skeleton
        else:
            self._node_list = self.skeleton.node_names

        self.endResetModel()

    def _valid_dst(self):
        # get source node using callback
        src_node = self._src_node()

        def is_valid_dst(node):
            # node cannot be dst of itself
            if node == src_node:
                return False
            # node cannot be dst if it's already dst of this src
            if (src_node, node) in self.skeleton.edge_names:
                return False
            return True

        # Filter down to valid destination nodes
        valid_dst_nodes = list(filter(is_valid_dst, self.skeleton.node_names))

        return valid_dst_nodes

    def data(self, index: QtCore.QModelIndex, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and index.isValid():
            idx = index.row()
            return self._node_list[idx]

        return None

    def rowCount(self, parent):
        return len(self._node_list)

    def columnCount(self, parent):
        return 1

    def flags(self, index: QtCore.QModelIndex):
        return Qt.ItemIsEnabled | Qt.ItemIsSelectable


if __name__ == "__main__":

    labels = load_labels_json_old("tests/data/json_format_v1/centered_pair.json")
    skeleton = labels.labels[0].instances[0].skeleton

    Labels.save_json(labels, "test.json")
    del labels
    labels = Labels.load_json("test.json")

    app = QApplication([])
    # table = SkeletonNodesTable(skeleton)
    # table = SkeletonEdgesTable(skeleton)
    # table = VideosTable(labels.videos)
    table = LabeledFrameTable(labels.labels[0])
    table.show()

    app.exec_()