from PySide2 import QtCore
from PySide2.QtCore import Qt

from PySide2.QtGui import QKeyEvent, QKeySequence

from PySide2.QtWidgets import QApplication, QMainWindow, QWidget, QDockWidget
from PySide2.QtWidgets import QVBoxLayout, QHBoxLayout, QGroupBox, QFormLayout
from PySide2.QtWidgets import QLabel, QPushButton, QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QCheckBox
from PySide2.QtWidgets import QTableWidget, QTableView, QTableWidgetItem
from PySide2.QtWidgets import QMenu, QAction
from PySide2.QtWidgets import QFileDialog, QMessageBox

import os
import sys

from pathlib import PurePath

import numpy as np
import pandas as pd

from sleap.skeleton import Skeleton, Node
from sleap.instance import Instance, Point
from sleap.io.video import Video, HDF5Video, MediaVideo
from sleap.io.dataset import Labels, LabeledFrame
from sleap.gui.video import QtVideoPlayer
from sleap.gui.dataviews import VideosTable, SkeletonNodesTable, SkeletonEdgesTable, LabeledFrameTable, SkeletonNodeModel
from sleap.gui.importvideos import ImportVideos

OPEN_IN_NEW = True

class MainWindow(QMainWindow):
    labels: Labels
    skeleton: Skeleton
    video: Video

    def __init__(self, data_path=None, video=None, import_data=None, *args, **kwargs):
        super(MainWindow, self).__init__(*args, **kwargs)

        # lines(7)*255
        self.cmap = np.array([
        [0,   114,   189],
        [217,  83,    25],
        [237, 177,    32],
        [126,  47,   142],
        [119, 172,    48],
        [77,  190,   238],
        [162,  20,    47],
        ])

        self.labels = Labels()
        self.skeleton = Skeleton()
        self.labeled_frame = None
        self.video = None
        self.video_idx = None
        self.mark_idx = None
        self.filename = None
        self.menuAction = dict()

        self._show_labels = True
        self._show_edges = True
        self._auto_zoom = False

        self.initialize_gui()

        if data_path is not None:
            pass

        if import_data is not None:
            self.importData(import_data)

        # TODO: auto-add video to clean project if no data provided
        # TODO: auto-select video if data provided, or add it to project
        if video is not None:
            self.addVideo(video)

    @property
    def filename(self):
        return self._filename

    @filename.setter
    def filename(self, x):
        self._filename = x
        self.setWindowTitle(x)

    def initialize_gui(self):

        ####### Video player #######
        self.player = QtVideoPlayer()
        self.player.changedPlot.connect(self.newFrame)
        self.setCentralWidget(self.player)

        ####### Status bar #######
        self.statusBar() # Initialize status bar

        ####### Menus #######
        fileMenu = self.menuBar().addMenu("File")
        fileMenu.addAction("&New Project", self.newProject, QKeySequence.New)
        fileMenu.addAction("&Open Project...", self.openProject, QKeySequence.Open)
        fileMenu.addAction("&Save", self.saveProject, QKeySequence.Save)
        fileMenu.addAction("Save As...", self.saveProjectAs, QKeySequence.SaveAs)
        fileMenu.addSeparator()
#         fileMenu.addAction("Import...").triggered.connect(self.importData)
#         fileMenu.addAction("Export...").triggered.connect(self.exportData)
#         fileMenu.addSeparator()
        fileMenu.addAction("&Quit", self.close)

        videoMenu = self.menuBar().addMenu("Video")
        # videoMenu.addAction("Check video encoding").triggered.connect(self.checkVideoEncoding)
        # videoMenu.addAction("Reencode for seeking").triggered.connect(self.reencodeForSeeking)
        # videoMenu.addSeparator()
        videoMenu.addAction("Add Videos...", self.addVideo, Qt.CTRL + Qt.Key_A)
        # videoMenu.addAction("Add folder").triggered.connect(self.addVideoFolder)
        videoMenu.addAction("Next Video", self.nextVideo, QKeySequence.Forward)
        videoMenu.addAction("Previous Video", self.previousVideo, QKeySequence.Back)
        videoMenu.addSeparator()
        videoMenu.addAction("Mark Frame", self.markFrame, Qt.CTRL + Qt.Key_M)
        videoMenu.addAction("Go to Marked Frame", self.goMarkedFrame, Qt.CTRL + Qt.SHIFT + Qt.Key_M)
        videoMenu.addAction("Extract Clip...", self.extractClip, Qt.CTRL + Qt.Key_E)

        labelMenu = self.menuBar().addMenu("Labels")
        labelMenu.addAction("Add Instance", self.newInstance, Qt.CTRL + Qt.Key_I)
        labelMenu.addAction("Transpose Instances", self.transposeInstance, Qt.CTRL + Qt.Key_T)
        labelMenu.addAction("Select Next Instance", self.player.view.nextSelection, QKeySequence(Qt.Key.Key_QuoteLeft))
        labelMenu.addAction("Clear Selection", self.player.view.clearSelection, QKeySequence(Qt.Key.Key_Escape))
        labelMenu.addSeparator()
        labelMenu.addAction("Next Labeled Frame", self.nextLabeledFrame, QKeySequence.FindNext)
        labelMenu.addAction("Previous Labeled Frame", self.previousLabeledFrame, QKeySequence.FindPrevious)
        labelMenu.addSeparator()
        self.menuAction["show labels"] = labelMenu.addAction("Show Node Names", self.toggleLabels, Qt.ALT + Qt.Key_Tab)
        self.menuAction["show edges"] = labelMenu.addAction("Show Edges", self.toggleEdges, Qt.ALT + Qt.SHIFT + Qt.Key_Tab)
        labelMenu.addSeparator()
        self.menuAction["fit"] = labelMenu.addAction("Fit Instances to View", self.toggleAutoZoom, Qt.CTRL + Qt.Key_Equal)

        self.menuAction["show labels"].setCheckable(True); self.menuAction["show labels"].setChecked(self._show_labels)
        self.menuAction["show edges"].setCheckable(True); self.menuAction["show edges"].setChecked(self._show_edges)
        self.menuAction["fit"].setCheckable(True)

        viewMenu = self.menuBar().addMenu("View")

        helpMenu = self.menuBar().addMenu("Help")
        helpMenu.addAction("Documentation", self.openDocumentation)
        helpMenu.addAction("Keyboard Reference", self.openKeyRef)
        helpMenu.addAction("About", self.openAbout)

        ####### Helpers #######
        def _make_dock(name, widgets=[], tab_with=None):
            dock = QDockWidget(name)
            dock.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
            dock_widget = QWidget()
            layout = QVBoxLayout()
            for widget in widgets:
                layout.addWidget(widget)
            dock_widget.setLayout(layout)
            dock.setWidget(dock_widget)
            self.addDockWidget(Qt.RightDockWidgetArea, dock)
            viewMenu.addAction(dock.toggleViewAction())
            if tab_with is not None:
                self.tabifyDockWidget(tab_with, dock)
            return layout

        ####### Videos #######
        videos_layout = _make_dock("Videos")
        self.videosTable = VideosTable()
        videos_layout.addWidget(self.videosTable)
        hb = QHBoxLayout()
        btn = QPushButton("Add videos")
        btn.clicked.connect(self.addVideo); hb.addWidget(btn)
        btn = QPushButton("Remove video")
        btn.clicked.connect(self.removeVideo); hb.addWidget(btn)
        hbw = QWidget(); hbw.setLayout(hb)
        videos_layout.addWidget(hbw)

        self.videosTable.doubleClicked.connect(lambda x: self.loadVideo(self.labels.videos[x.row()], x.row()))

        ####### Skeleton #######
        skeleton_layout = _make_dock("Skeleton", tab_with=videos_layout.parent().parent())

        gb = QGroupBox("Nodes")
        vb = QVBoxLayout()
        self.skeletonNodesTable = SkeletonNodesTable(self.skeleton)
        vb.addWidget(self.skeletonNodesTable)
        hb = QHBoxLayout()
        btn = QPushButton("New node")
        btn.clicked.connect(self.newNode); hb.addWidget(btn)
        btn = QPushButton("Delete node")
        btn.clicked.connect(self.deleteNode); hb.addWidget(btn)
        hbw = QWidget(); hbw.setLayout(hb)
        vb.addWidget(hbw)
        gb.setLayout(vb)
        skeleton_layout.addWidget(gb)

        gb = QGroupBox("Edges")
        vb = QVBoxLayout()
        self.skeletonEdgesTable = SkeletonEdgesTable(self.skeleton)
        vb.addWidget(self.skeletonEdgesTable)
        hb = QHBoxLayout()
        self.skeletonEdgesSrc = QComboBox(); self.skeletonEdgesSrc.setEditable(False); self.skeletonEdgesSrc.currentIndexChanged.connect(self.selectSkeletonEdgeSrc)
        self.skeletonEdgesSrc.setModel(SkeletonNodeModel(self.skeleton))
        hb.addWidget(self.skeletonEdgesSrc)
        self.skeletonEdgesDst = QComboBox(); self.skeletonEdgesDst.setEditable(False)
        hb.addWidget(self.skeletonEdgesDst)
        self.skeletonEdgesDst.setModel(SkeletonNodeModel(self.skeleton, lambda: self.skeletonEdgesSrc.currentText()))
        btn = QPushButton("Add edge")
        btn.clicked.connect(self.newEdge); hb.addWidget(btn)
        btn = QPushButton("Delete edge")
        btn.clicked.connect(self.deleteEdge); hb.addWidget(btn)
        hbw = QWidget(); hbw.setLayout(hb)
        vb.addWidget(hbw)
        gb.setLayout(vb)
        skeleton_layout.addWidget(gb)

        # update edge UI when change to nodes
        self.skeletonNodesTable.model().dataChanged.connect(self.updateEdges)

        ####### Instances #######
        instances_layout = _make_dock("Instances")
        self.instancesTable = LabeledFrameTable()
        instances_layout.addWidget(self.instancesTable)
        hb = QHBoxLayout()
        btn = QPushButton("New instance")
        btn.clicked.connect(self.newInstance); hb.addWidget(btn)
        btn = QPushButton("Delete instance")
        btn.clicked.connect(self.deleteInstance); hb.addWidget(btn)
        hbw = QWidget(); hbw.setLayout(hb)
        instances_layout.addWidget(hbw)

        ####### Points #######
        # points_layout = _make_dock("Points", tab_with=instances_layout.parent().parent())
        # self.pointsTable = _make_table(["id", "frameIdx", "instanceId", "x", "y", "node", "visible"])
        # # self.pointsTable = _make_table_df(self.labels.points)
        # points_layout.addWidget(self.pointsTable)

        ####### Training #######
        training_layout = _make_dock("Training")
        gb = QGroupBox("Data representation")
        fl = QFormLayout()
        self.dataRange = QComboBox(); self.dataRange.addItems(["[0, 1]", "[-1, 1]"]); self.dataRange.setEditable(False)
        fl.addRow("Range:", self.dataRange)
        # TODO: range ([0, 1], [-1, 1])
        # TODO: normalization (z-score, CLAHE)
        self.dataScale = QDoubleSpinBox(); self.dataScale.setMinimum(0.25); self.dataScale.setValue(1.0)
        fl.addRow("Scale:", self.dataScale)

        gb.setLayout(fl)
        training_layout.addWidget(gb)

        gb = QGroupBox("Augmentation")
        fl = QFormLayout()
        self.augmentationRotation = QDoubleSpinBox(); self.augmentationRotation.setRange(0, 180); self.augmentationRotation.setValue(15.0)
        fl.addRow("Rotation:", self.augmentationRotation)
        self.augmentationFlipH = QCheckBox()
        fl.addRow("Flip (horizontal):", self.augmentationFlipH)
        # self.augmentationScaling = QDoubleSpinBox(); self.augmentationScaling.setRange(0.1, 2); self.augmentationScaling.setValue(1.0)
        # fl.addRow("Scaling:", self.augmentationScaling)
        gb.setLayout(fl)
        training_layout.addWidget(gb)

        gb = QGroupBox("Confidence maps")
        fl = QFormLayout()
        self.confmapsArchitecture = QComboBox(); self.confmapsArchitecture.addItems(["leap_cnn", "unet", "hourglass", "stacked_hourglass"]); self.confmapsArchitecture.setCurrentIndex(1); self.confmapsArchitecture.setEditable(False)
        fl.addRow("Architecture:", self.confmapsArchitecture)
        self.confmapsFilters = QSpinBox(); self.confmapsFilters.setMinimum(1); self.confmapsFilters.setValue(32)
        fl.addRow("Filters:", self.confmapsFilters)
        self.confmapsDepth = QSpinBox(); self.confmapsDepth.setMinimum(1); self.confmapsDepth.setValue(3)
        fl.addRow("Depth:", self.confmapsDepth)
        self.confmapsSigma = QDoubleSpinBox(); self.confmapsSigma.setMinimum(0.1); self.confmapsSigma.setValue(5.0)
        fl.addRow("Sigma:", self.confmapsSigma)
        btn = QPushButton("Train"); btn.clicked.connect(self.trainConfmaps)
        fl.addRow(btn)
        gb.setLayout(fl)
        training_layout.addWidget(gb)

        gb = QGroupBox("PAFs")
        fl = QFormLayout()
        self.pafsArchitecture = QComboBox(); self.pafsArchitecture.addItems(["leap_cnn", "unet", "hourglass", "stacked_hourglass"]); self.pafsArchitecture.setEditable(False)
        fl.addRow("Architecture:", self.pafsArchitecture)
        self.pafsFilters = QSpinBox(); self.pafsFilters.setMinimum(1); self.pafsFilters.setValue(32)
        fl.addRow("Filters:", self.pafsFilters)
        self.pafsDepth = QSpinBox(); self.pafsDepth.setMinimum(1); self.pafsDepth.setValue(3)
        fl.addRow("Depth:", self.pafsDepth)
        self.pafsSigma = QDoubleSpinBox(); self.pafsSigma.setMinimum(0.1); self.pafsSigma.setValue(5.0)
        fl.addRow("Sigma:", self.pafsSigma)
        btn = QPushButton("Train"); btn.clicked.connect(self.trainPAFs)
        fl.addRow(btn)
        gb.setLayout(fl)
        training_layout.addWidget(gb)


    def keyPressEvent(self, event: QKeyEvent):
        if event.key() == Qt.Key_Q:
            self.close()
        else:
            event.ignore() # Kicks the event up to parent

    def plotFrame(self, *args, **kwargs):
        """Wrap call to player.plot so we can redraw/update things."""
        self.player.plot(*args, **kwargs)
        self.player.showLabels(self._show_labels)
        self.player.showEdges(self._show_edges)
        if self._auto_zoom:
            self.player.zoomToFit()

    def importData(self, filename=None):
        show_msg = False
        # if filename is None:
#         if not isinstance(filename, str):
#             filters = ["JSON labels (*.json)", "HDF5 dataset (*.h5 *.hdf5)"]
#             # filename, selected_filter = QFileDialog.getOpenFileName(self, dir="C:/Users/tdp/OneDrive/code/sandbox/leap_wt_gold_pilot", caption="Import labeled data...", filter=";;".join(filters))
#             filename, selected_filter = QFileDialog.getOpenFileName(self, dir=None, caption="Import labeled data...", filter=";;".join(filters))
#             show_msg = True

        if len(filename) == 0: return

        self.filename = filename

        if filename.endswith(".json"):
            self.labels = Labels.load_json(filename)

            if show_msg:
                msgBox = QMessageBox(text=f"Imported {len(self.labels)} labeled frames.")
                msgBox.exec_()

            # Update UI tables
            self.videosTable.model().videos = self.labels.videos
            if len(self.labels.labels) > 0:
                if len(self.labels.labels[0].instances) > 0:
                    self.skeleton = self.labels.labels[0].instances[0].skeleton
                    self.skeletonNodesTable.model().skeleton = self.skeleton
                    self.skeletonEdgesTable.model().skeleton = self.skeleton
                    self.skeletonEdgesSrc.model().skeleton = self.skeleton
                    self.skeletonEdgesDst.model().skeleton = self.skeleton

            # Load first video
            self.loadVideo(self.labels.videos[0], 0)

    def addVideo(self, filename=None):
        # Browse for file
        video = None
        if isinstance(filename, str):
            video = Video.from_filename(filename)
            # Add to labels
            self.labels.add_video(video)
        else:
            import_list = ImportVideos().go()
            for import_item in import_list:
                # Create Video object
                video = Video.from_filename(**import_item["params"])
                # Add to labels
                self.labels.add_video(video)

        # Load if no video currently loaded
        if self.video is None:
            self.loadVideo(video, len(self.labels.videos)-1)

        # Update data model/view
        self.videosTable.model().videos = self.labels.videos

    def removeVideo(self):
        # Get selected video
        idx = self.videosTable.currentIndex()
        if not idx.isValid(): return
        video = self.labels.videos[idx.row()]

        # Count labeled frames for this video
        n = len(self.labels.find(video))

        # Warn if there are labels that will be deleted
        if n > 0:
            response = QMessageBox.critical(self, "Removing video with labels", f"{n} labeled frames in this video will be deleted, are you sure you want to remove this video?", QMessageBox.Yes, QMessageBox.No)
            if response == QMessageBox.No:
                return

        # Remove video
        self.labels.remove_video(video)

        # TODO: Update data model?
        self.videosTable.model().videos = self.labels.videos

        # Update view if this was the current video
        if self.video == video:
            if len(self.labels.videos) == 0:
                self.player.reset()
                # TODO: update statusbar
            else:
                new_idx = min(idx.row(), len(self.labels.videos) - 1)
                self.loadVideo(self.labels.videos[new_idx], new_idx)

    def loadVideo(self, video:Video, video_idx: int = None):
        # Clear video frame mark
        self.mark_idx = None

        # Update current video instance
        self.video = video
        self.video_idx = video_idx if video_idx is not None else self.video_idx

        # Load video in player widget
        self.player.load_video(self.video)

        # Jump to last labeled frame
        last_label = self.labels.find_last(self.video)
        if last_label is not None:
            self.plotFrame(last_label.frame_idx)


    def newNode(self):
        # Find new part name
        part_name = "new_part"
        i = 1
        while part_name in self.skeleton:
            part_name = f"new_part_{i}"
            i += 1

        # Add the node to the skeleton
        self.skeleton.add_node(part_name)

        # Update data model
        self.skeletonNodesTable.model().skeleton = self.skeleton

        # Update source edges dropdown
        self.skeletonEdgesSrc.model().skeleton = self.skeleton

        self.plotFrame()

    def deleteNode(self):
        # Get selected node
        idx = self.skeletonNodesTable.currentIndex()
        if not idx.isValid(): return
        node = self.skeleton.nodes[idx.row()]

        # Remove
        self.skeleton.delete_node(node)

        # Update data model
        self.skeletonNodesTable.model().skeleton = self.skeleton

        # Update edges dropdown
        self.skeletonEdgesSrc.model().skeleton = self.skeleton

        # TODO: Replot instances?
        self.plotFrame()

    def selectSkeletonEdgeSrc(self):
        self.skeletonEdgesDst.model().skeleton = self.skeleton

    def updateEdges(self):
        self.skeletonEdgesTable.model().skeleton = self.skeleton
        self.skeletonEdgesSrc.model().skeleton = self.skeleton
        self.skeletonEdgesDst.model().skeleton = self.skeleton
        self.plotFrame()

    def newEdge(self):
        # TODO: Move this to unified data model

        # Get selected nodes
        src_node = self.skeletonEdgesSrc.currentText()
        dst_node = self.skeletonEdgesDst.currentText()

        # Check if they're in the graph
        if src_node not in self.skeleton or dst_node not in self.skeleton:
            return

        # Add edge
        self.skeleton.add_edge(source=src_node, destination=dst_node)

        # Update data model
        self.skeletonEdgesTable.model().skeleton = self.skeleton

        self.plotFrame()


    def deleteEdge(self):
        # TODO: Move this to unified data model

        # Get selected edge
        idx = self.skeletonEdgesTable.currentIndex()
        if not idx.isValid(): return
        edge = self.skeleton.edges[idx.row()]

        # Delete edge
        self.skeleton.delete_edge(source=edge[0], destination=edge[1])

        # Update data model
        self.skeletonEdgesTable.model().skeleton = self.skeleton

        self.plotFrame()


    def newInstance(self):
        if self.labeled_frame is None:
            return

        new_instance = Instance(skeleton=self.skeleton)
        for node in self.skeleton.nodes:
            new_instance[node] = Point(x=np.random.rand() * self.video.width * 0.5, y=np.random.rand() * self.video.height * 0.5, visible=True)
        self.labeled_frame.instances.append(new_instance)

        if self.labeled_frame not in self.labels.labels:
            self.labels.append(self.labeled_frame)

        self.plotFrame()

    def deleteInstance(self):
        idx = self.instancesTable.currentIndex()
        if not idx.isValid(): return
        del self.labeled_frame.instances[idx.row()]

        self.plotFrame()

    def transposeInstance(self):
        # We're currently identifying instances by numeric index, so it's
        # impossible to (e.g.) have a single instance which we identify
        # as the second instance in some other frame.
        
        # For the present, we can only "transpose" if there are multiple instances.
        if len(self.labeled_frame.instances) < 2: return
        # If there are just two instances, transpose them.
        if len(self.labeled_frame.instances) == 2:
            self._transpose_instances((0,1))
        # If there are more than two, then we need the user to select the instances.
        else:
            self.player.onSequenceSelect(seq_len = 2,
                                         on_success = self._transpose_instances,
                                         on_each = self._transpose_message,
                                         on_failure = lambda x:self.updateStatusMessage()
                                         )

    def _transpose_message(self, instance_ids:list):
        word = "next" if len(instance_ids) else "first"
        self.updateStatusMessage(f"Please select the {word} instance to transpose...")

    def _transpose_instances(self, instance_ids:list):
        if len(instance_ids) != 2: return
        
        idx_0 = instance_ids[0]
        idx_1 = instance_ids[1]
        self.labeled_frame.instances[idx_0], self.labeled_frame.instances[idx_1] = (
            self.labeled_frame.instances[idx_1], self.labeled_frame.instances[idx_0])
            
        self.plotFrame()

    def newProject(self):
        window = MainWindow()
        window.showMaximized()

    def openProject(self):
        filters = ["JSON labels (*.json)", "HDF5 dataset (*.h5 *.hdf5)"]
        filename, selected_filter = QFileDialog.getOpenFileName(self, dir=None, caption="Import labeled data...", filter=";;".join(filters))

        if len(filename) == 0: return

        if OPEN_IN_NEW:
            new_window = MainWindow()
            new_window.showMaximized()
            new_window.importData(filename)
        else:
            self.importData(filename)

    def saveProject(self):
        if self.filename is not None:
            filename = self.filename
            if filename.endswith(".json"):
                Labels.save_json(labels = self.labels, filename = filename)
            # Redraw. Not sure why, but sometimes we need to do this.
            self.plotFrame()

    def saveProjectAs(self):
        default_name = self.filename if self.filename is not None else "untitled.json"
        p = PurePath(default_name)
        default_name = str(p.with_name(f"{p.stem} copy{p.suffix}"))

        filters = ["JSON labels (*.json)", "HDF5 dataset (*.h5 *.hdf5)"]
        filename, selected_filter = QFileDialog.getSaveFileName(self, caption="Save As...", dir=default_name, filter=";;".join(filters))

        if len(filename) == 0: return

        if filename.endswith(".json"):
            Labels.save_json(labels = self.labels, filename = filename)
            self.filename = filename
            # Redraw. Not sure why, but sometimes we need to do this.
            self.plotFrame()
        else:
            QMessageBox(text=f"File not saved. Only .json currently implemented.")

    def exportData(self):
        pass
    # def close(self):
        # pass
    def checkVideoEncoding(self):
        pass
    def reencodeForSeeking(self):
        pass
    def addVideoFolder(self):
        pass
    def nextVideo(self):
        new_idx = self.video_idx+1
        new_idx = 0 if new_idx >= len(self.labels.videos) else new_idx
        self.loadVideo(self.labels.videos[new_idx], new_idx)

    def previousVideo(self):
        new_idx = self.video_idx-1
        new_idx = len(self.labels.videos)-1 if new_idx < 0 else new_idx
        self.loadVideo(self.labels.videos[new_idx], new_idx)

    def markFrame(self):
        self.mark_idx = self.player.frame_idx

    def goMarkedFrame(self):
        self.plotFrame(self.mark_idx)

    def extractClip(self):
        if self.mark_idx is None:
            QMessageBox(text=f"You must first mark a frame to determine the range for extraction.").exec_()
        else:
            start = min(self.mark_idx, self.player.frame_idx)
            end = max(self.mark_idx, self.player.frame_idx)
            QMessageBox(text=f"Extract video frames: {start+1} to {end+1}. Not yet implemented.").exec_()

    def previousLabeledFrame(self):
        cur_idx = self.player.frame_idx
        frame_indexes = [frame.frame_idx for frame in self.labels.find(self.video)]
        if len(frame_indexes):
            prev_idx = max(filter(lambda idx: idx < cur_idx, frame_indexes), default=frame_indexes[-1])
            self.plotFrame(prev_idx)

    def nextLabeledFrame(self):
        cur_idx = self.player.frame_idx
        frame_indexes = [frame.frame_idx for frame in self.labels.find(self.video)]
        if len(frame_indexes):
            next_idx = min(filter(lambda idx: idx > cur_idx, frame_indexes), default=frame_indexes[0])
            self.plotFrame(next_idx)

    def toggleLabels(self):
        self._show_labels = not self._show_labels
        self.menuAction["show labels"].setChecked(self._show_labels)
        self.player.showLabels(self._show_labels)

    def toggleEdges(self):
        self._show_edges = not self._show_edges
        self.menuAction["show edges"].setChecked(self._show_edges)
        self.player.showEdges(self._show_edges)

    def toggleAutoZoom(self):
        self._auto_zoom = not self._auto_zoom
        self.menuAction["fit"].setChecked(self._auto_zoom)
        if not self._auto_zoom:
            self.player.view.clearZoom()
        self.plotFrame()

    def openDocumentation(self):
        pass
    def openKeyRef(self):
        pass
    def openAbout(self):
        pass


    def trainConfmaps(self):
        from sleap.nn.datagen import generate_images, generate_confidence_maps
        from sleap.nn.training import train

        imgs, keys = generate_images(self.labels)
        confmaps, _keys, points = generate_confidence_maps(self.labels)

        self.confmapModel = train(imgs, confmaps, test_size=0.1, batch_norm=False, num_filters=64, batch_size=4, num_epochs=100, steps_per_epoch=100)

    def trainPAFs(self):
        pass


    def newFrame(self, player, frame_idx):

        labeled_frame = [label for label in self.labels.labels if label.video == self.video and label.frame_idx == frame_idx]
        self.labeled_frame = labeled_frame[0] if len(labeled_frame) > 0 else LabeledFrame(video=self.video, frame_idx=frame_idx)
        self.instancesTable.model().labeled_frame = self.labeled_frame

        for i, instance in enumerate(self.labeled_frame.instances):
            player.addInstance(instance=instance, color=self.cmap[i%len(self.cmap)])

        player.view.updatedViewer.emit()

        self.updateStatusMessage()

    def updateStatusMessage(self, message = None):
        if message is None:
            message = f"Frame: {self.player.frame_idx+1}/{len(self.video)}"

        self.statusBar().showMessage(message)
        # self.statusBar().showMessage(f"Frame: {self.player.frame_idx+1}/{len(self.video)}  |  Labeled frames (video/total): {self.labels.instances[self.labels.instances.videoId == 1].frameIdx.nunique()}/{len(self.labels)}  |  Instances (frame/total): {len(frame_instances)}/{self.labels.points.instanceId.nunique()}")

def main(*args, **kwargs):
    app = QApplication([])
    app.setApplicationName("sLEAP Label")

    if "import_data" not in kwargs:
        filters = ["JSON labels (*.json)", "HDF5 dataset (*.h5 *.hdf5)"]
        filename, selected_filter = QFileDialog.getOpenFileName(None, dir=None, caption="Open Project", filter=";;".join(filters))

        if len(filename): kwargs["import_data"] = filename

    window = MainWindow(*args, **kwargs)
    window.showMaximized()
    app.exec_()

if __name__ == "__main__":

    kwargs = dict()
    if len(sys.argv) > 1:
        kwargs["import_data"] = sys.argv[1]

    main(**kwargs)
