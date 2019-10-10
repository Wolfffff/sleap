"""
Module for running active learning (or just inference) from GUI.
"""

import os
import cattr

from datetime import datetime
from functools import reduce
from pkg_resources import Requirement, resource_filename
from typing import Dict, List, Optional, Tuple

from sleap.io.dataset import Labels
from sleap.io.video import Video
from sleap.gui.filedialog import FileDialog
from sleap.gui.training_editor import TrainingEditor
from sleap.gui.formbuilder import YamlFormWidget
from sleap.nn.model import ModelOutputType
from sleap.nn.training import TrainingJob

from PySide2 import QtWidgets, QtCore


SELECT_FILE_OPTION = "Select a training profile file..."


class ActiveLearningDialog(QtWidgets.QDialog):
    """Active learning dialog.

    The dialog can be used in different modes:
    * simplified active learning (fewer controls)
    * expert active learning (full controls)
    * inference only

    Arguments:
        labels_filename: Path to the dataset where we'll get training data.
        labels: The dataset where we'll get training data and add predictions.
        mode: String which specified mode ("active", "expert", or "inference").
    """

    learningFinished = QtCore.Signal()

    def __init__(
        self,
        labels_filename: str,
        labels: Labels,
        mode: str = "expert",
        *args,
        **kwargs,
    ):

        super(ActiveLearningDialog, self).__init__(*args, **kwargs)

        self.labels_filename = labels_filename
        self.labels = labels
        self.mode = mode
        self._job_filter = None

        if self.mode == "inference":
            self._job_filter = lambda job: job.is_trained

        print(f"Number of frames to train on: {len(labels.user_labeled_frames)}")

        title = dict(
            learning="Active Learning",
            inference="Inference",
            expert="Inference Pipeline",
        )

        learning_yaml = resource_filename(
            Requirement.parse("sleap"), "sleap/config/active.yaml"
        )
        self.form_widget = YamlFormWidget(
            yaml_file=learning_yaml,
            which_form=self.mode,
            title=title[self.mode] + " Settings",
        )

        # form ui

        self.training_profile_widgets = dict()

        if "conf_job" in self.form_widget.fields:
            self.training_profile_widgets[
                ModelOutputType.CONFIDENCE_MAP
            ] = self.form_widget.fields["conf_job"]
        if "paf_job" in self.form_widget.fields:
            self.training_profile_widgets[
                ModelOutputType.PART_AFFINITY_FIELD
            ] = self.form_widget.fields["paf_job"]
        if "centroid_job" in self.form_widget.fields:
            self.training_profile_widgets[
                ModelOutputType.CENTROIDS
            ] = self.form_widget.fields["centroid_job"]

        self._rebuild_job_options()
        self._update_job_menus(init=True)

        buttons = QtWidgets.QDialogButtonBox()
        self.cancel_button = buttons.addButton(QtWidgets.QDialogButtonBox.Cancel)
        self.run_button = buttons.addButton(
            "Run " + title[self.mode], QtWidgets.QDialogButtonBox.AcceptRole
        )

        self.status_message = QtWidgets.QLabel("hi!")

        buttons_layout = QtWidgets.QHBoxLayout()
        buttons_layout.addWidget(self.status_message)
        buttons_layout.addWidget(buttons, alignment=QtCore.Qt.AlignTop)

        buttons_layout_widget = QtWidgets.QWidget()
        buttons_layout_widget.setLayout(buttons_layout)

        layout = QtWidgets.QVBoxLayout()
        layout.addWidget(self.form_widget)
        layout.addWidget(buttons_layout_widget)

        self.setLayout(layout)

        # connect actions to buttons

        def edit_conf_profile():
            self._view_profile(
                self.form_widget["conf_job"], model_type=ModelOutputType.CONFIDENCE_MAP
            )

        def edit_paf_profile():
            self._view_profile(
                self.form_widget["paf_job"],
                model_type=ModelOutputType.PART_AFFINITY_FIELD,
            )

        def edit_cent_profile():
            self._view_profile(
                self.form_widget["centroid_job"], model_type=ModelOutputType.CENTROIDS
            )

        if "_view_conf" in self.form_widget.buttons:
            self.form_widget.buttons["_view_conf"].clicked.connect(edit_conf_profile)
        if "_view_paf" in self.form_widget.buttons:
            self.form_widget.buttons["_view_paf"].clicked.connect(edit_paf_profile)
        if "_view_centoids" in self.form_widget.buttons:
            self.form_widget.buttons["_view_centoids"].clicked.connect(
                edit_cent_profile
            )
        if "_view_datagen" in self.form_widget.buttons:
            self.form_widget.buttons["_view_datagen"].clicked.connect(self.view_datagen)

        self.form_widget.valueChanged.connect(lambda: self.update_gui())

        buttons.accepted.connect(self.run)
        buttons.rejected.connect(self.reject)

        self.update_gui()

    def _rebuild_job_options(self):
        """
        Rebuilds list of profile options (checking for new profile files).
        """
        # load list of job profiles from directory
        profile_dir = resource_filename(
            Requirement.parse("sleap"), "sleap/training_profiles"
        )

        self.job_options = dict()

        # list any profiles from previous runs
        if self.labels_filename:
            labels_dir = os.path.join(os.path.dirname(self.labels_filename), "models")
            if os.path.exists(labels_dir):
                find_saved_jobs(labels_dir, self.job_options)
        # list default profiles
        find_saved_jobs(profile_dir, self.job_options)

        # Apply any filters
        if self._job_filter:
            for model_type, jobs_list in self.job_options.items():
                self.job_options[model_type] = [
                    (path, job) for (path, job) in jobs_list if self._job_filter(job)
                ]

    def _update_job_menus(self, init: bool = False):
        """Updates the menus with training profile options.

        Args:
            init: Whether this is first time calling (so we should connect
                signals), or we're just updating menus.

        Returns:
            None.
        """
        for model_type, field in self.training_profile_widgets.items():
            if model_type not in self.job_options:
                self.job_options[model_type] = []
            if init:

                def menu_action(idx, mt=model_type, field=field):
                    self._update_from_selected_job(mt, idx, field)

                field.currentIndexChanged.connect(menu_action)
            else:
                # block signals so we can update combobox without overwriting
                # any user data with the defaults from the profile
                field.blockSignals(True)
            field.set_options(self._option_list_from_jobs(model_type))
            # enable signals again so that choice of profile will update params
            field.blockSignals(False)

    @property
    def frame_selection(self) -> Dict[Video, List[int]]:
        """
        Returns dictionary with frames that user has selected for inference.
        """
        return self._frame_selection

    @frame_selection.setter
    def frame_selection(self, frame_selection: Dict[str, Dict[Video, List[int]]]):
        """Sets options of frames on which to run inference."""
        self._frame_selection = frame_selection

        if "_predict_frames" in self.form_widget.fields.keys():
            prediction_options = []

            def count_total_frames(videos_frames):
                return reduce(lambda x, y: x + y, map(len, videos_frames.values()))

            # Determine which options are available given _frame_selection

            total_random = count_total_frames(self._frame_selection["random"])
            total_suggestions = count_total_frames(self._frame_selection["suggestions"])
            clip_length = count_total_frames(self._frame_selection["clip"])
            video_length = count_total_frames(self._frame_selection["video"])

            # Build list of options

            prediction_options.append("current frame")

            option = f"random frames ({total_random} total frames)"
            prediction_options.append(option)
            default_option = option

            if total_suggestions > 0:
                option = f"suggested frames ({total_suggestions} total frames)"
                prediction_options.append(option)
                default_option = option

            if clip_length > 0:
                option = f"selected clip ({clip_length} frames)"
                prediction_options.append(option)
                default_option = option

            prediction_options.append(f"entire video ({video_length} frames)")

            self.form_widget.fields["_predict_frames"].set_options(
                prediction_options, default_option
            )

    def show(self):
        """Shows dialog (we hide rather than close to maintain settings)."""
        super(ActiveLearningDialog, self).show()

        # TODO: keep selection and any items added from training editor

        self._rebuild_job_options()
        self._update_job_menus()

    def update_gui(self):
        """Updates gui state after user changes to options."""
        form_data = self.form_widget.get_form_data()

        can_run = True

        if "_use_centroids" in self.form_widget.fields:
            use_centroids = form_data.get("_use_centroids", False)

            if form_data.get("_use_trained_centroids", False):
                # you must use centroids if you are using a centroid model
                use_centroids = True
                self.form_widget.set_form_data(dict(_use_centroids=True))
                self.form_widget.fields["_use_centroids"].setEnabled(False)
            else:
                self.form_widget.fields["_use_centroids"].setEnabled(True)

            if use_centroids:
                # you must crop if you are using centroids
                self.form_widget.set_form_data(dict(instance_crop=True))
                self.form_widget.fields["instance_crop"].setEnabled(False)
            else:
                self.form_widget.fields["instance_crop"].setEnabled(True)

        error_messages = []
        if form_data.get("_use_trained_confmaps", False) and form_data.get(
            "_use_trained_pafs", False
        ):
            # make sure trained models are compatible
            conf_job, _ = self._get_current_job(ModelOutputType.CONFIDENCE_MAP)
            paf_job, _ = self._get_current_job(ModelOutputType.PART_AFFINITY_FIELD)

            # only check compatible if we have both profiles
            if conf_job is not None and paf_job is not None:
                if conf_job.trainer.scale != paf_job.trainer.scale:
                    can_run = False
                    error_messages.append(
                        f"training image scale for confmaps ({conf_job.trainer.scale}) does not match pafs ({paf_job.trainer.scale})"
                    )
                if conf_job.trainer.instance_crop != paf_job.trainer.instance_crop:
                    can_run = False
                    crop_model_name = (
                        "confmaps" if conf_job.trainer.instance_crop else "pafs"
                    )
                    error_messages.append(
                        f"exactly one model ({crop_model_name}) was trained on crops"
                    )
                if use_centroids and not conf_job.trainer.instance_crop:
                    can_run = False
                    error_messages.append(
                        f"models used with centroids must be trained on cropped images"
                    )

        message = ""
        if not can_run:
            message = (
                "Unable to run with selected models:\n- "
                + ";\n- ".join(error_messages)
                + "."
            )
        self.status_message.setText(message)

        self.run_button.setEnabled(can_run)

    def _get_current_job(self, model_type: ModelOutputType) -> Tuple[TrainingJob, str]:
        """Returns training job currently selected for given model type.

        Args:
            model_type: The type of model for which we want data.

        Returns: Tuple of (TrainingJob, path to job profile).
        """
        # by default use the first model for a given type
        idx = 0
        if model_type in self.training_profile_widgets:
            field = self.training_profile_widgets[model_type]
            idx = field.currentIndex()

        # Check that selection corresponds to something we're loaded
        # (it won't when user is adding a new profile)
        if idx >= len(self.job_options[model_type]):
            return None, None

        job_filename, job = self.job_options[model_type][idx]

        if model_type == ModelOutputType.CENTROIDS:
            # reload centroid profile since we always want to use this
            # rather than any scale and such entered by user
            job = TrainingJob.load_json(job_filename)

        return job, job_filename

    def _get_model_types_to_use(self):
        """Returns lists of model types which user has enabled."""
        form_data = self.form_widget.get_form_data()
        types_to_use = []

        # always include confidence maps
        types_to_use.append(ModelOutputType.CONFIDENCE_MAP)

        # by default we want to use part affinity fields
        if not form_data.get("_dont_use_pafs", False):
            types_to_use.append(ModelOutputType.PART_AFFINITY_FIELD)

        # by default we want to use centroids
        if form_data.get("_use_centroids", True):
            types_to_use.append(ModelOutputType.CENTROIDS)

        return types_to_use

    def _get_current_training_jobs(self) -> Dict[ModelOutputType, TrainingJob]:
        """Returns all currently selected training jobs."""
        form_data = self.form_widget.get_form_data()
        training_jobs = dict()

        default_use_trained = self.mode == "inference"

        for model_type in self._get_model_types_to_use():
            job, _ = self._get_current_job(model_type)

            if job is None:
                continue

            if job.model.output_type != ModelOutputType.CENTROIDS:
                # update training job from params in form
                trainer = job.trainer
                for key, val in form_data.items():
                    # check if field name is [var]_[model_type] (eg sigma_confmaps)
                    if key.split("_")[-1] == str(model_type):
                        key = "_".join(key.split("_")[:-1])
                    # check if form field matches attribute of Trainer object
                    if key in dir(trainer):
                        setattr(trainer, key, val)
            # Use already trained model if desired
            if form_data.get(f"_use_trained_{str(model_type)}", default_use_trained):
                job.use_trained_model = True

            training_jobs[model_type] = job

        return training_jobs

    def run(self):
        """Run active learning (or inference) with current dialog settings."""
        # Collect TrainingJobs and params from form
        form_data = self.form_widget.get_form_data()
        training_jobs = self._get_current_training_jobs()

        # Close the dialog now that we have the data from it
        self.accept()

        with_tracking = False
        predict_frames_choice = form_data.get("_predict_frames", "")
        if predict_frames_choice.startswith("current frame"):
            frames_to_predict = self._frame_selection["frame"]
        elif predict_frames_choice.startswith("random"):
            frames_to_predict = self._frame_selection["random"]
        elif predict_frames_choice.startswith("selected clip"):
            frames_to_predict = self._frame_selection["clip"]
            with_tracking = True
        elif predict_frames_choice.startswith("suggested"):
            frames_to_predict = self._frame_selection["suggestions"]
        elif predict_frames_choice.startswith("entire video"):
            frames_to_predict = self._frame_selection["video"]
            with_tracking = True
        else:
            frames_to_predict = dict()

        save_predictions = form_data.get("_save_predictions", False)

        # Run active learning pipeline using the TrainingJobs
        new_counts = run_active_learning_pipeline(
            labels_filename=self.labels_filename,
            labels=self.labels,
            training_jobs=training_jobs,
            frames_to_predict=frames_to_predict,
            with_tracking=with_tracking,
            save_predictions=save_predictions,
        )

        self.learningFinished.emit()

        QtWidgets.QMessageBox(
            text=f"Active learning has finished. Instances were predicted on {new_counts} frames."
        ).exec_()

    def view_datagen(self):
        """Shows windows with sample visual data that will be used training."""
        from sleap.nn.datagen import (
            generate_training_data,
            generate_confmaps_from_points,
            generate_pafs_from_points,
        )
        from sleap.io.video import Video
        from sleap.gui.overlays.confmaps import demo_confmaps
        from sleap.gui.overlays.pafs import demo_pafs

        conf_job, _ = self._get_current_job(ModelOutputType.CONFIDENCE_MAP)

        # settings for datagen
        form_data = self.form_widget.get_form_data()
        scale = form_data.get("scale", conf_job.trainer.scale)
        sigma = form_data.get("sigma", None)
        sigma_confmaps = form_data.get("sigma_confmaps", sigma)
        sigma_pafs = form_data.get("sigma_pafs", sigma)
        instance_crop = form_data.get("instance_crop", conf_job.trainer.instance_crop)
        min_crop_size = form_data.get("min_crop_size", 0)
        negative_samples = form_data.get("negative_samples", 0)

        imgs, points = generate_training_data(
            self.labels,
            params=dict(
                frame_limit=10,
                scale=scale,
                instance_crop=instance_crop,
                min_crop_size=min_crop_size,
                negative_samples=negative_samples,
            ),
        )

        skeleton = self.labels.skeletons[0]
        img_shape = (imgs.shape[1], imgs.shape[2])
        vid = Video.from_numpy(imgs * 255)

        confmaps = generate_confmaps_from_points(
            points, skeleton, img_shape, sigma=sigma_confmaps
        )
        conf_win = demo_confmaps(confmaps, vid)
        conf_win.activateWindow()
        conf_win.move(200, 200)

        pafs = generate_pafs_from_points(points, skeleton, img_shape, sigma=sigma_pafs)
        paf_win = demo_pafs(pafs, vid)
        paf_win.activateWindow()
        paf_win.move(220 + conf_win.rect().width(), 200)

        # FIXME: hide dialog so use can see other windows
        # can we show these windows without closing dialog?
        self.hide()

    def _view_profile(self, filename: str, model_type: ModelOutputType, windows=[]):
        """Opens profile editor in new dialog window."""
        saved_files = []
        win = TrainingEditor(filename, saved_files=saved_files, parent=self)
        windows.append(win)
        win.exec_()

        for new_filename in saved_files:
            self._add_job_file_to_list(new_filename, model_type)

    def _option_list_from_jobs(self, model_type: ModelOutputType):
        """Returns list of menu options for given model type."""
        jobs = self.job_options[model_type]
        option_list = [name for (name, job) in jobs]
        option_list.append("")
        option_list.append("---")
        option_list.append(SELECT_FILE_OPTION)
        return option_list

    def _add_job_file(self, model_type):
        """Allow user to add training profile for given model type."""
        filename, _ = FileDialog.open(
            None,
            dir=None,
            caption="Select training profile...",
            filter="TrainingJob JSON (*.json)",
        )

        self._add_job_file_to_list(filename, model_type)
        field = self.training_profile_widgets[model_type]
        # if we didn't successfully select a new file, then clear selection
        if field.currentIndex() == field.count() - 1:  # subtract 1 for separator
            field.setCurrentIndex(-1)

    def _add_job_file_to_list(self, filename: str, model_type: ModelOutputType):
        """Adds selected training profile for given model type."""
        if len(filename):
            try:
                # try to load json as TrainingJob
                job = TrainingJob.load_json(filename)
            except:
                # but do raise any other type of error
                QtWidgets.QMessageBox(
                    text=f"Unable to load a training profile from {filename}."
                ).exec_()
                raise
            else:
                # we loaded the json as a TrainingJob, so see what type of model it's for
                file_model_type = job.model.output_type
                # make sure the users selected a file with the right model type
                if model_type == file_model_type:
                    # insert at beginning of list
                    self.job_options[model_type].insert(0, (filename, job))
                    # update ui list
                    if model_type in self.training_profile_widgets:
                        field = self.training_profile_widgets[model_type]
                        field.set_options(
                            self._option_list_from_jobs(model_type), filename
                        )
                else:
                    QtWidgets.QMessageBox(
                        text=f"Profile selected is for training {str(file_model_type)} instead of {str(model_type)}."
                    ).exec_()

    def _update_from_selected_job(self, model_type: ModelOutputType, idx: int, field):
        """Updates dialog settings after user selects a training profile."""
        jobs = self.job_options[model_type]
        field_text = field.currentText()
        if idx == -1:
            return
        if idx < len(jobs):
            name, job = jobs[idx]

            training_params = cattr.unstructure(job.trainer)
            training_params_specific = {
                f"{key}_{str(model_type)}": val for key, val in training_params.items()
            }
            # confmap and paf models should share some params shown in dialog (e.g. scale)
            # but centroids does not, so just set any centroid_foo fields from its profile
            if model_type in [ModelOutputType.CENTROIDS]:
                training_params = training_params_specific
            else:
                training_params = {**training_params, **training_params_specific}
            self.form_widget.set_form_data(training_params)

            # is the model already trained?
            is_trained = job.is_trained
            field_name = f"_use_trained_{str(model_type)}"
            # update "use trained" checkbox if present
            if field_name in self.form_widget.fields:
                self.form_widget.fields[field_name].setEnabled(is_trained)
                self.form_widget[field_name] = is_trained
        elif field_text == SELECT_FILE_OPTION:
            self._add_job_file(model_type)


def make_default_training_jobs() -> Dict[ModelOutputType, TrainingJob]:
    """Creates TrainingJobs with some default settings."""
    from sleap.nn.model import Model
    from sleap.nn.training import Trainer
    from sleap.nn.architectures import unet, leap

    # Build Models (wrapper for Keras model with some metadata)

    models = dict()
    models[ModelOutputType.CONFIDENCE_MAP] = Model(
        output_type=ModelOutputType.CONFIDENCE_MAP, backbone=unet.UNet(num_filters=32)
    )
    models[ModelOutputType.PART_AFFINITY_FIELD] = Model(
        output_type=ModelOutputType.PART_AFFINITY_FIELD,
        backbone=leap.LeapCNN(num_filters=64),
    )

    # Build Trainers

    defaults = dict()
    defaults["shared"] = dict(
        instance_crop=True,
        val_size=0.1,
        augment_rotation=180,
        batch_size=4,
        learning_rate=1e-4,
        reduce_lr_factor=0.5,
        reduce_lr_cooldown=3,
        reduce_lr_min_delta=1e-6,
        reduce_lr_min_lr=1e-10,
        amsgrad=True,
        shuffle_every_epoch=True,
        save_every_epoch=False,
        #             val_batches_per_epoch = 10,
        #             upsampling_layers = True,
        #             depth = 3,
    )
    defaults[ModelOutputType.CONFIDENCE_MAP] = dict(
        **defaults["shared"], num_epochs=100, steps_per_epoch=200, reduce_lr_patience=5
    )

    defaults[ModelOutputType.PART_AFFINITY_FIELD] = dict(
        **defaults["shared"], num_epochs=75, steps_per_epoch=100, reduce_lr_patience=8
    )

    trainers = dict()
    for type in models.keys():
        trainers[type] = Trainer(**defaults[type])

    # Build TrainingJobs from Models and Trainers

    training_jobs = dict()
    for type in models.keys():
        training_jobs[type] = TrainingJob(models[type], trainers[type])

    return training_jobs


def find_saved_jobs(
    job_dir: str, jobs=None
) -> Dict[ModelOutputType, List[Tuple[str, TrainingJob]]]:
    """Find all the TrainingJob json files in a given directory.

    Args:
        job_dir: the directory in which to look for json files
        jobs: If given, then the found jobs will be added to this object,
            rather than creating new dict.
    Returns:
        dict of {ModelOutputType: list of (filename, TrainingJob) tuples}
    """

    files = os.listdir(job_dir)

    json_files = [os.path.join(job_dir, f) for f in files if f.endswith(".json")]
    # sort newest to oldest
    json_files.sort(key=lambda f: os.path.getmtime(f), reverse=True)

    jobs = dict() if jobs is None else jobs
    for full_filename in json_files:
        try:
            # try to load json as TrainingJob
            job = TrainingJob.load_json(full_filename)
        except ValueError:
            # couldn't load as TrainingJob so just ignore this json file
            # probably it's a json file for something else
            pass
        except:
            # but do raise any other type of error
            raise
        else:
            # we loaded the json as a TrainingJob, so see what type of model it's for
            model_type = job.model.output_type
            if model_type not in jobs:
                jobs[model_type] = []
            jobs[model_type].append((full_filename, job))

    return jobs


def run_active_learning_pipeline(
    labels_filename: str,
    labels: Labels,
    training_jobs: Dict["ModelOutputType", "TrainingJob"] = None,
    frames_to_predict: Dict[Video, List[int]] = None,
    with_tracking: bool = False,
    save_predictions: bool = False,
) -> int:
    """Run training (as needed) and inference.

    Args:
        labels_filename: Path to already saved current labels object.
        labels: The current labels object; results will be added to this.
        training_jobs: The TrainingJobs with params/hyperparams for training.
        frames_to_predict: Dict that gives list of frame indices for each video.
        with_tracking: Whether to run tracking code after we predict instances.
            This should be used only when predicting on continuous set of frames.
        save_predictions: Whether to save new predictions in separate file.

    Returns:
        Number of new frames added to labels.

    """

    # Prepare our TrainingJobs

    # Load the defaults we use for active learning
    if training_jobs is None:
        training_jobs = make_default_training_jobs()

    # Set the parameters specific to this run
    for job in training_jobs.values():
        job.labels_filename = labels_filename

    if labels_filename:
        save_dir = os.path.join(os.path.dirname(labels_filename), "models")

    # If there are jobs to train and no path to save them, ask for path
    if (has_jobs_to_train or save_predictions) and not labels_filename:
        save_dir = FileDialog.openDir(
            None, directory=None, caption="Please select directory for saving files..."
        )

        if not save_dir:
            raise ValueError("No valid directory for saving files.")

    # Train the TrainingJobs
    trained_jobs = run_active_training(labels, training_jobs, save_dir)

    # Check that all the models were trained
    if None in trained_jobs.values():
        return 0

    # Clear save_dir if we don't want to save predictions in new file
    if not save_predictions:
        save_dir = ""

    # Run the Predictor for suggested frames
    new_labeled_frame_count = run_active_inference(
        labels, trained_jobs, save_dir, frames_to_predict, with_tracking
    )

    return new_labeled_frame_count


def has_jobs_to_train(training_jobs: Dict["ModelOutputType", "TrainingJob"]):
    """Returns whether any of the jobs need to be trained."""
    return any(not getattr(job, "use_trained_model", False) for job in training_jobs)


def run_active_training(
    labels: Labels,
    training_jobs: Dict["ModelOutputType", "TrainingJob"],
    save_dir: str,
    gui: bool = True,
) -> Dict["ModelOutputType", "TrainingJob"]:
    """
    Run training for each training job.

    Args:
        labels: Labels object from which we'll get training data.
        training_jobs: Dict of the jobs to train.
        save_dir: Path to the directory where we'll save inference results.
        gui: Whether to show gui windows and process gui events.

    Returns:
        Dict of trained jobs corresponding with input training jobs.
    """

    trained_jobs = dict()

    if gui:
        from sleap.nn.monitor import LossViewer

        # open training monitor window
        win = LossViewer()
        win.resize(600, 400)
        win.show()

    for model_type, job in training_jobs.items():
        if getattr(job, "use_trained_model", False):
            # set path to TrainingJob already trained from previous run
            json_name = f"{job.run_name}.json"
            trained_jobs[model_type] = os.path.join(job.save_dir, json_name)
            print(f"Using already trained model: {trained_jobs[model_type]}")

        else:
            if gui:
                print("Resetting monitor window.")
                win.reset(what=str(model_type))
                win.setWindowTitle(f"Training Model - {str(model_type)}")

            print(f"Start training {str(model_type)}...")

            # Start training in separate process
            # This makes it easier to ensure that tensorflow released memory when done
            pool, result = job.trainer.train_async(
                model=job.model, labels=labels, save_dir=save_dir
            )

            # Wait for training results
            while not result.ready():
                if gui:
                    QtWidgets.QApplication.instance().processEvents()
                result.wait(0.01)

            if result.successful():
                # get the path to the resulting TrainingJob file
                trained_jobs[model_type] = result.get()
                print(f"Finished training {str(model_type)}.")
            else:
                if gui:
                    win.close()
                    QtWidgets.QMessageBox(
                        text=f"An error occured while training {str(model_type)}. Your command line terminal may have more information about the error."
                    ).exec_()
                trained_jobs[model_type] = None
                result.get()

    # Load the jobs we just trained
    for model_type, job in trained_jobs.items():
        # Replace path to saved TrainingJob with the deseralized object
        if trained_jobs[model_type] is not None:
            trained_jobs[model_type] = TrainingJob.load_json(trained_jobs[model_type])

    if gui:
        # close training monitor window
        win.close()

    return trained_jobs


def run_active_inference(
    labels: Labels,
    training_jobs: Dict["ModelOutputType", "TrainingJob"],
    save_dir: str,
    frames_to_predict: Dict[Video, List[int]],
    with_tracking: bool,
    gui: bool = True,
) -> int:
    """Run inference on specified frames using models from training_jobs.

    Args:
        labels: The current labels object; results will be added to this.
        training_jobs: The TrainingJobs with trained models to use.
        save_dir: Path to the directory where we'll save inference results.
        frames_to_predict: Dict that gives list of frame indices for each video.
        with_tracking: Whether to run tracking code after we predict instances.
            This should be used only when predicting on continuous set of frames.
        gui: Whether to show gui windows and process gui events.

    Returns:
        Number of new frames added to labels.
    """
    from sleap.nn.inference import Predictor

    # Create Predictor from the results of training
    predictor = Predictor(training_jobs=training_jobs, with_tracking=with_tracking)

    if gui:
        # show message while running inference
        progress = QtWidgets.QProgressDialog(
            f"Running inference on {len(frames_to_predict)} videos...",
            "Cancel",
            0,
            len(frames_to_predict),
        )
        # win.setLabelText("    Running inference on selected frames...    ")
        progress.show()
        QtWidgets.QApplication.instance().processEvents()

    new_lfs = []
    for i, (video, frames) in enumerate(frames_to_predict.items()):
        QtWidgets.QApplication.instance().processEvents()
        if len(frames):
            # Run inference for desired frames in this video
            # result = predictor.predict_async(
            new_lfs_video = predictor.predict(input_video=video, frames=frames)
            new_lfs.extend(new_lfs_video)

        if gui:
            progress.setValue(i)
            if progress.wasCanceled():
                return 0

            # while not result.ready():
            #     if gui:
            #         QtWidgets.QApplication.instance().processEvents()
            #     result.wait(.01)

            # if result.successful():
            # new_labels_json = result.get()

            # Add new frames to labels
            # (we're doing this for each video as we go since there was a problem
            # when we tried to add frames for all videos together.)
            # new_lf_count = add_frames_from_json(labels, new_labels_json)

            # total_new_lf_count += new_lf_count
            # else:
            # if gui:
            #     QtWidgets.QApplication.instance().processEvents()
            #     QtWidgets.QMessageBox(text=f"An error occured during inference. Your command line terminal may have more information about the error.").exec_()
            # result.get()

    # predictor.pool.close()

    # Remove any frames without instances
    new_lfs = list(filter(lambda lf: len(lf.instances), new_lfs))

    # Create dataset with predictions
    new_labels = Labels(new_lfs)

    # Save dataset of predictions (if desired)
    if save_dir:
        timestamp = datetime.now().strftime("%y%m%d_%H%M%S")
        inference_output_path = os.path.join(save_dir, f"{timestamp}.inference.h5")
        Labels.save_file(new_labels, inference_output_path)

    # Merge predictions into current labels dataset
    _, _, new_conflicts = Labels.complex_merge_between(labels, new_labels)

    # new predictions should replace old ones
    Labels.finish_complex_merge(labels, new_conflicts)

    # close message window
    if gui:
        progress.close()

    # return total_new_lf_count
    return len(new_lfs)


if __name__ == "__main__":
    import sys

    #     labels_filename = "/Volumes/fileset-mmurthy/nat/shruthi/labels-mac.json"
    labels_filename = sys.argv[1]
    labels = Labels.load_json(labels_filename)

    app = QtWidgets.QApplication()
    win = ActiveLearningDialog(labels=labels, labels_filename=labels_filename)
    win.show()
    app.exec_()

#     labeled_frames = run_active_learning_pipeline(labels_filename)
#     print(labeled_frames)
