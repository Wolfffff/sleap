""" Video reading and writing interfaces for different formats. """

import os
import shutil

import h5py as h5
import cv2
import imgstore
import numpy as np
import attr
import cattr
import logging

from typing import Iterable, Union, List, Tuple

logger = logging.getLogger(__name__)


@attr.s(auto_attribs=True, cmp=False)
class HDF5Video:
    """
    Video data stored as 4D datasets in HDF5 files.

    Args:
        filename: The name of the HDF5 file where the dataset with video data
            is stored.
        dataset: The name of the HDF5 dataset where the video data is stored.
        file_h5: The h5.File object that the underlying dataset is stored.
        dataset_h5: The h5.Dataset object that the underlying data is stored.
        input_format: A string value equal to either "channels_last" or
            "channels_first".
            This specifies whether the underlying video data is stored as:

                * "channels_first": shape = (frames, channels, width, height)
                * "channels_last": shape = (frames, width, height, channels)
        convert_range: Whether we should convert data to [0, 255]-range
    """

    filename: str = attr.ib(default=None)
    dataset: str = attr.ib(default=None)
    input_format: str = attr.ib(default="channels_last")
    convert_range: bool = attr.ib(default=True)

    def __attrs_post_init__(self):
        """Called by attrs after __init__()."""

        self.__original_to_current_frame_idx = dict()

        # Handle cases where the user feeds in h5.File objects instead of filename
        if isinstance(self.filename, h5.File):
            self.__file_h5 = self.filename
            self.filename = self.__file_h5.filename
        elif type(self.filename) is str:
            try:
                self.__file_h5 = h5.File(self.filename, "r")
            except OSError as ex:
                raise FileNotFoundError(
                    f"Could not find HDF5 file {self.filename}"
                ) from ex
        else:
            self.__file_h5 = None

        # Handle the case when h5.Dataset is passed in
        if isinstance(self.dataset, h5.Dataset):
            self.__dataset_h5 = self.dataset
            self.__file_h5 = self.__dataset_h5.file
            self.dataset = self.__dataset_h5.name

        # File loaded and dataset name given, so load dataset
        elif isinstance(self.dataset, str) and (self.__file_h5 is not None):
            self.__dataset_h5 = self.__file_h5[self.dataset]

            # Check for frame_numbers dataset corresponding to video
            base_dataset_path = "/".join(self.dataset.split("/")[:-1])
            framenum_dataset = f"{base_dataset_path}/frame_numbers"
            if framenum_dataset in self.__file_h5:
                original_idx_lists = self.__file_h5[framenum_dataset]
                # Create map from idx in original video to idx in current
                for current_idx in range(len(original_idx_lists)):
                    original_idx = original_idx_lists[current_idx]
                    self.__original_to_current_frame_idx[original_idx] = current_idx

        else:
            self.__dataset_h5 = None

    @input_format.validator
    def check(self, attribute, value):
        """Called by attrs to validates input format."""
        if value not in ["channels_first", "channels_last"]:
            raise ValueError(f"HDF5Video input_format={value} invalid.")

        if value == "channels_first":
            self.__channel_idx = 1
            self.__width_idx = 2
            self.__height_idx = 3
        else:
            self.__channel_idx = 3
            self.__width_idx = 2
            self.__height_idx = 1

    def matches(self, other: "HDF5Video") -> bool:
        """
        Check if attributes match those of another video.

        Args:
            other: The other video to compare with.

        Returns:
            True if attributes match, False otherwise.
        """
        return (
            self.filename == other.filename
            and self.dataset == other.dataset
            and self.convert_range == other.convert_range
            and self.input_format == other.input_format
        )

    def close(self):
        """Closes the HDF5 file object (if it's open)."""
        if self.__file_h5:
            try:
                self.__file_h5.close()
            except:
                pass
            self.__file_h5 = None

    def __del__(self):
        """Releases file object."""
        self.close()

    # The properties and methods below complete our contract with the
    # higher level Video interface.

    @property
    def frames(self):
        """See :class:`Video`."""
        return self.__dataset_h5.shape[0]

    @property
    def channels(self):
        """See :class:`Video`."""
        if "channels" in self.__dataset_h5.attrs:
            return int(self.__dataset_h5.attrs["channels"])
        return self.__dataset_h5.shape[self.__channel_idx]

    @property
    def width(self):
        """See :class:`Video`."""
        if "width" in self.__dataset_h5.attrs:
            return int(self.__dataset_h5.attrs["width"])
        return self.__dataset_h5.shape[self.__width_idx]

    @property
    def height(self):
        """See :class:`Video`."""
        if "height" in self.__dataset_h5.attrs:
            return int(self.__dataset_h5.attrs["height"])
        return self.__dataset_h5.shape[self.__height_idx]

    @property
    def dtype(self):
        """See :class:`Video`."""
        return self.__dataset_h5.dtype

    @property
    def last_frame_idx(self) -> int:
        """
        The idx number of the last frame.

        Overrides method of base :class:`Video` class for videos with
        select frames indexed by number from original video, since the last
        frame index here will not match the number of frames in video.
        """
        if self.__original_to_current_frame_idx:
            last_key = sorted(self.__original_to_current_frame_idx.keys())[-1]
            return last_key
        return self.frames - 1

    def get_frame(self, idx) -> np.ndarray:
        """
        Get a frame from the underlying HDF5 video data.

        Args:
            idx: The index of the frame to get.

        Returns:
            The numpy.ndarray representing the video frame data.
        """
        # If we only saved some frames from a video, map to idx in dataset.
        if self.__original_to_current_frame_idx:
            if idx in self.__original_to_current_frame_idx:
                idx = self.__original_to_current_frame_idx[idx]
            else:
                raise ValueError(f"Frame index {idx} not in original index.")

        frame = self.__dataset_h5[idx]

        if self.__dataset_h5.attrs.get("format", ""):
            frame = cv2.imdecode(frame, cv2.IMREAD_UNCHANGED)

            # Add dimension for single channel (dropped by opencv).
            if frame.ndim == 2:
                frame = frame[..., np.newaxis]

        if self.input_format == "channels_first":
            frame = np.transpose(frame, (2, 1, 0))

        if self.convert_range and np.max(frame) <= 1.0:
            frame = (frame * 255).astype(int)

        return frame


@attr.s(auto_attribs=True, cmp=False)
class MediaVideo:
    """
    Video data stored in traditional media formats readable by FFMPEG

    This class provides bare minimum read only interface on top of
    OpenCV's VideoCapture class.

    Args:
        filename: The name of the file (.mp4, .avi, etc)
        grayscale: Whether the video is grayscale or not. "auto" means detect
            based on first frame.
        bgr: Whether color channels ordered as (blue, green, red).
    """

    filename: str = attr.ib()
    grayscale: bool = attr.ib()
    bgr: bool = attr.ib(default=True)
    _detect_grayscale = False
    _reader_ = None
    _test_frame_ = None
    _frame_count = None

    @grayscale.default
    def __grayscale_default__(self):
        self._detect_grayscale = True
        return False

    @property
    def __reader(self):
        # Load if not already loaded
        if self._reader_ is None:
            if not os.path.isfile(self.filename):
                raise FileNotFoundError(
                    f"Could not find filename video filename named {self.filename}"
                )

            # Try and open the file either locally in current directory or with full path
            self._reader_ = cv2.VideoCapture(self.filename)

            # If the user specified None for grayscale bool, figure it out based on the
            # the first frame of data.
            if self._detect_grayscale is True:
                self.grayscale = bool(
                    np.alltrue(self.__test_frame[..., 0] == self.__test_frame[..., -1])
                )

        # Return cached reader
        return self._reader_

    @property
    def __test_frame(self):
        # Load if not already loaded
        if self._test_frame_ is None:
            # Lets grab a test frame to help us figure things out about the video
            test_idx = self.frames // 2
            self._test_frame_ = self.get_frame(test_idx, grayscale=False)

        # Return stored test frame
        return self._test_frame_

    def matches(self, other: "MediaVideo") -> bool:
        """
        Check if attributes match those of another video.

        Args:
            other: The other video to compare with.

        Returns:
            True if attributes match, False otherwise.
        """
        return (
            self.filename == other.filename
            and self.grayscale == other.grayscale
            and self.bgr == other.bgr
        )

    @property
    def fps(self) -> float:
        """Returns frames per second of video."""
        return self.__reader.get(cv2.CAP_PROP_FPS)

    def is_valid_frame(self, frame_idx):
        """
        Checks whether we consistently get same frame data for frame index.

        Some non-"seekable" videos will have bad frames at the beginning and/or
        end. If we try to access these frames, we get different data (or no
        data) each time.

        Args:
            frame_idx: The frame index to check.

        Returns:
            True if we get consistent data when loading frame.
        """
        try:
            return np.all(self.get_frame(frame_idx) == self.get_frame(frame_idx))
        except TypeError:
            return False

    @property
    def accurate_frame_count(self) -> int:
        """Returns frame count by searching for last valid frame."""
        # Get the frame count from the video metadata
        purported_count = int(self.__reader.get(cv2.CAP_PROP_FRAME_COUNT))

        # Check that we can load the last frame
        if self.is_valid_frame(purported_count - 1):
            return purported_count

        # Since we can't load last frame, there must be some bad frames at
        # the end of the video.

        # Find a margin large enough to contain all the invalid frames.
        margin = 64
        while not self.is_valid_frame(purported_count - margin):
            margin *= 2
            if margin > purported_count:
                return 0

        # Now do binary search between margin and purported end to find last
        # valid frame.
        x = purported_count - margin
        step = margin // 2
        while step > 1:
            x = x + step if self.is_valid_frame(x) else x - step
            step = step // 2
        return x

    # The properties and methods below complete our contract with the
    # higher level Video interface.

    @property
    def frames(self):
        """See :class:`Video`."""
        if self._frame_count is None:
            # Cache frame count since this may require checking frame data.
            self._frame_count = self.accurate_frame_count
        return self._frame_count

    @property
    def channels(self):
        """See :class:`Video`."""
        if self.grayscale:
            return 1
        else:
            return self.__test_frame.shape[2]

    @property
    def width(self):
        """See :class:`Video`."""
        return self.__test_frame.shape[1]

    @property
    def height(self):
        """See :class:`Video`."""
        return self.__test_frame.shape[0]

    @property
    def dtype(self):
        """See :class:`Video`."""
        return self.__test_frame.dtype

    def get_frame(self, idx: int, grayscale: bool = None) -> np.ndarray:
        """See :class:`Video`."""
        if self.__reader.get(cv2.CAP_PROP_POS_FRAMES) != idx:
            self.__reader.set(cv2.CAP_PROP_POS_FRAMES, idx)

        ret, frame = self.__reader.read()

        if grayscale is None:
            grayscale = self.grayscale

        if grayscale:
            frame = frame[..., 0][..., None]

        if self.bgr:
            frame = frame[..., ::-1]

        return frame


@attr.s(auto_attribs=True, cmp=False)
class NumpyVideo:
    """
    Video data stored as Numpy array.

    Args:
        filename: Either a file to load or a numpy array of the data.

        * numpy data shape: (frames, width, height, channels)
    """

    filename: attr.ib()

    def __attrs_post_init__(self):

        self.__frame_idx = 0
        self.__width_idx = 1
        self.__height_idx = 2
        self.__channel_idx = 3

        # Handle cases where the user feeds in np.array instead of filename
        if isinstance(self.filename, np.ndarray):
            self.__data = self.filename
            self.filename = "Raw Video Data"
        elif type(self.filename) is str:
            try:
                self.__data = np.load(self.filename)
            except OSError as ex:
                raise FileNotFoundError(
                    f"Could not find filename {self.filename}"
                ) from ex
        else:
            self.__data = None

    # The properties and methods below complete our contract with the
    # higher level Video interface.

    def matches(self, other: "NumpyVideo") -> np.ndarray:
        """
        Check if attributes match those of another video.

        Args:
            other: The other video to compare with.

        Returns:
            True if attributes match, False otherwise.
        """
        return np.all(self.__data == other.__data)

    @property
    def frames(self):
        """See :class:`Video`."""
        return self.__data.shape[self.__frame_idx]

    @property
    def channels(self):
        """See :class:`Video`."""
        return self.__data.shape[self.__channel_idx]

    @property
    def width(self):
        """See :class:`Video`."""
        return self.__data.shape[self.__width_idx]

    @property
    def height(self):
        """See :class:`Video`."""
        return self.__data.shape[self.__height_idx]

    @property
    def dtype(self):
        """See :class:`Video`."""
        return self.__data.dtype

    def get_frame(self, idx):
        """See :class:`Video`."""
        return self.__data[idx]


@attr.s(auto_attribs=True, cmp=False)
class ImgStoreVideo:
    """
    Video data stored as an ImgStore dataset.

    See: https://github.com/loopbio/imgstore
    This class is just a lightweight wrapper for reading such datasets as
    video sources for SLEAP.

    Args:
        filename: The name of the file or directory to the imgstore.
        index_by_original: ImgStores are great for storing a collection of
            selected frames from an larger video. If the index_by_original is
            set to True then the get_frame function will accept the original
            frame numbers of from original video. If False, then it will
            accept the frame index from the store directly.
            Default to True so that we can use an ImgStoreVideo in a dataset
            to replace another video without having to update all the frame
            indices on :class:`LabeledFrame` objects in the dataset.
    """

    filename: str = attr.ib(default=None)
    index_by_original: bool = attr.ib(default=True)
    _store_ = None
    _img_ = None

    def __attrs_post_init__(self):

        # If the filename does not contain metadata.yaml, append it to the filename
        # assuming that this is a directory that contains the imgstore.
        if "metadata.yaml" not in self.filename:
            # Use "/" since this works on Windows and posix
            self.filename = self.filename + "/metadata.yaml"

        # Make relative path into absolute, ImgStores don't work properly it seems
        # without full paths if we change working directories. Video.fixup_path will
        # fix this later when loading these datasets.
        self.filename = os.path.abspath(self.filename)

        self.__store = None

    # The properties and methods below complete our contract with the
    # higher level Video interface.

    def matches(self, other):
        """
        Check if attributes match.

        Args:
            other: The instance to comapare with.

        Returns:
            True if attributes match, False otherwise
        """
        return (
            self.filename == other.filename
            and self.index_by_original == other.index_by_original
        )

    @property
    def __store(self):
        if self._store_ is None:
            self.open()
        return self._store_

    @__store.setter
    def __store(self, val):
        self._store_ = val

    @property
    def __img(self):
        if self._img_ is None:
            self.open()
        return self._img_

    @property
    def frames(self):
        """See :class:`Video`."""
        return self.__store.frame_count

    @property
    def channels(self):
        """See :class:`Video`."""
        if len(self.__img.shape) < 3:
            return 1
        else:
            return self.__img.shape[2]

    @property
    def width(self):
        """See :class:`Video`."""
        return self.__img.shape[1]

    @property
    def height(self):
        """See :class:`Video`."""
        return self.__img.shape[0]

    @property
    def dtype(self):
        """See :class:`Video`."""
        return self.__img.dtype

    @property
    def last_frame_idx(self) -> int:
        """
        The idx number of the last frame.

        Overrides method of base :class:`Video` class for videos with
        select frames indexed by number from original video, since the last
        frame index here will not match the number of frames in video.
        """
        if self.index_by_original:
            return self.__store.frame_max
        return self.frames - 1

    def get_frame(self, frame_number: int) -> np.ndarray:
        """
        Get a frame from the underlying ImgStore video data.

        Args:
            frame_number: The number of the frame to get. If
                index_by_original is set to True, then this number should
                actually be a frame index within the imgstore. That is,
                if there are 4 frames in the imgstore, this number should be
                be from 0 to 3.

        Returns:
            The numpy.ndarray representing the video frame data.
        """

        # Check if we need to open the imgstore and do it if needed
        if not self._store_:
            self.open()

        if self.index_by_original:
            img, (frame_number, frame_timestamp) = self.__store.get_image(frame_number)
        else:
            img, (frame_number, frame_timestamp) = self.__store.get_image(
                frame_number=None, frame_index=frame_number
            )

        # If the frame has one channel, add a singleton channel as it seems other
        # video implementations do this.
        if img.ndim == 2:
            img = img[:, :, None]

        return img

    @property
    def imgstore(self):
        """
        Get the underlying ImgStore object for this Video.

        Returns:
            The imgstore that is backing this video object.
        """
        return self.__store

    def open(self):
        """
        Open the image store if it isn't already open.

        Returns:
            None
        """
        if not self._store_:
            # Open the imgstore
            self._store_ = imgstore.new_for_filename(self.filename)

            # Read a frame so we can compute shape an such
            self._img_, (frame_number, frame_timestamp) = self._store_.get_next_image()

    def close(self):
        """
        Close the imgstore if it isn't already closed.

        Returns:
            None
        """
        if self.imgstore:
            # Open the imgstore
            self.__store.close()
            self.__store = None


@attr.s(auto_attribs=True, cmp=False)
class Video:
    """
    The top-level interface to any Video data used by SLEAP.

    This class provides a common interface for various supported video data
    backends. It provides the bare minimum of properties and methods that
    any video data needs to support in order to function with other SLEAP
    components. This interface currently only supports reading of video
    data, there is no write support. Unless one is creating a new video
    backend, this class should be instantiated from its various class methods
    for different formats. For example:

    >>> video = Video.from_hdf5(filename="test.h5", dataset="box")
    >>> video = Video.from_media(filename="test.mp4")

    Or we can use auto-detection based on filename:

    >>> video = Video.from_filename(filename="test.mp4")

    Args:
        backend: A backend is an object that implements the following basic
            required methods and properties

        * Properties

            * :code:`frames`: The number of frames in the video
            * :code:`channels`: The number of channels in the video
              (e.g. 1 for grayscale, 3 for RGB)
            * :code:`width`: The width of each frame in pixels
            * :code:`height`: The height of each frame in pixels

        * Methods

            * :code:`get_frame(frame_index: int) -> np.ndarray`:
              Get a single frame from the underlying video data with
              output shape=(width, height, channels).

    """

    backend: Union[HDF5Video, NumpyVideo, MediaVideo, ImgStoreVideo] = attr.ib()

    # Delegate to the backend
    def __getattr__(self, item):
        return getattr(self.backend, item)

    @property
    def num_frames(self) -> int:
        """
        The number of frames in the video. Just an alias for frames property.
        """
        return self.frames

    @property
    def last_frame_idx(self) -> int:
        """
        The idx number of the last frame. Usually `numframes - 1`.
        """
        if hasattr(self.backend, "last_frame_idx"):
            return self.backend.last_frame_idx
        return self.frames - 1

    @property
    def shape(self) -> Tuple[int, int, int, int]:
        """ Returns (frame count, height, width, channels)."""
        return (self.frames, self.height, self.width, self.channels)

    def __str__(self):
        """ Informal string representation (for print or format) """
        return type(self).__name__ + " ([%d x %d x %d x %d])" % self.shape

    def __len__(self):
        """
        The length of the video should be the number of frames.

        Returns:
            The number of frames in the video.
        """
        return self.frames

    def get_frame(self, idx: int) -> np.ndarray:
        """
        Return a single frame of video from the underlying video data.

        Args:
            idx: The index of the video frame

        Returns:
            The video frame with shape (width, height, channels)
        """
        return self.backend.get_frame(idx)

    def get_frames(self, idxs: Union[int, Iterable[int]]) -> np.ndarray:
        """
        Return a collection of video frames from the underlying video data.

        Args:
            idxs: An iterable object that contains the indices of frames.

        Returns:
            The requested video frames with shape
            (len(idxs), width, height, channels)
        """
        if np.isscalar(idxs):
            idxs = [idxs]
        return np.stack([self.get_frame(idx) for idx in idxs], axis=0)

    def __getitem__(self, idxs):
        if isinstance(idxs, slice):
            start, stop, step = idxs.indices(self.num_frames)
            idxs = range(start, stop, step)
        return self.get_frames(idxs)

    @classmethod
    def from_hdf5(
        cls,
        dataset: Union[str, h5.Dataset],
        filename: Union[str, h5.File] = None,
        input_format: str = "channels_last",
        convert_range: bool = True,
    ) -> "Video":
        """
        Create an instance of a video object from an HDF5 file and dataset.

        This is a helper method that invokes the HDF5Video backend.

        Args:
            dataset: The name of the dataset or and h5.Dataset object. If
                filename is h5.File, dataset must be a str of the dataset name.
            filename: The name of the HDF5 file or and open h5.File object.
            input_format: Whether the data is oriented with "channels_first"
                or "channels_last"
            convert_range: Whether we should convert data to [0, 255]-range

        Returns:
            A Video object with HDF5Video backend.
        """
        filename = Video.fixup_path(filename)
        backend = HDF5Video(
            filename=filename,
            dataset=dataset,
            input_format=input_format,
            convert_range=convert_range,
        )
        return cls(backend=backend)

    @classmethod
    def from_numpy(cls, filename: str, *args, **kwargs) -> "Video":
        """
        Create an instance of a video object from a numpy array.

        Args:
            filename: The numpy array or the name of the file
            args: Arguments to pass to :class:`NumpyVideo`
            kwargs: Arguments to pass to :class:`NumpyVideo`

        Returns:
            A Video object with a NumpyVideo backend
        """
        filename = Video.fixup_path(filename)
        backend = NumpyVideo(filename=filename, *args, **kwargs)
        return cls(backend=backend)

    @classmethod
    def from_media(cls, filename: str, *args, **kwargs) -> "Video":
        """
        Create an instance of a video object from a typical media file.

        For example, mp4, avi, or other types readable by FFMPEG.

        Args:
            filename: The name of the file
            args: Arguments to pass to :class:`MediaVideo`
            kwargs: Arguments to pass to :class:`MediaVideo`

        Returns:
            A Video object with a MediaVideo backend
        """
        filename = Video.fixup_path(filename)
        backend = MediaVideo(filename=filename, *args, **kwargs)
        return cls(backend=backend)

    @classmethod
    def from_filename(cls, filename: str, *args, **kwargs) -> "Video":
        """
        Create an instance of a video object, auto-detecting the backend.

        Args:
            filename: The path to the video filename.
                Currently supported types are:

                * Media Videos - AVI, MP4, etc. handled by OpenCV directly
                * HDF5 Datasets - .h5 files
                * Numpy Arrays - npy files
                * imgstore datasets - produced by loopbio's Motif recording
                    system. See: https://github.com/loopbio/imgstore.

            args: Arguments to pass to :class:`NumpyVideo`
            kwargs: Arguments to pass to :class:`NumpyVideo`

        Returns:
            A Video object with the detected backend.
        """

        filename = Video.fixup_path(filename)

        if filename.lower().endswith(("h5", "hdf5")):
            return cls(backend=HDF5Video(filename=filename, *args, **kwargs))
        elif filename.endswith(("npy")):
            return cls(backend=NumpyVideo(filename=filename, *args, **kwargs))
        elif filename.lower().endswith(("mp4", "avi")):
            return cls(backend=MediaVideo(filename=filename, *args, **kwargs))
        elif os.path.isdir(filename) or "metadata.yaml" in filename:
            return cls(backend=ImgStoreVideo(filename=filename, *args, **kwargs))
        else:
            raise ValueError("Could not detect backend for specified filename.")

    @classmethod
    def imgstore_from_filenames(
        cls, filenames: list, output_filename: str, *args, **kwargs
    ) -> "Video":
        """Create an imgstore from a list of image files.

        Args:
            filenames: List of filenames for the image files.
            output_filename: Filename for the imgstore to create.

        Returns:
            A `Video` object for the new imgstore.
        """

        # get the image size from the first file
        first_img = cv2.imread(filenames[0], flags=cv2.IMREAD_COLOR)
        img_shape = first_img.shape

        # create the imgstore
        store = imgstore.new_for_format(
            "png", mode="w", basedir=output_filename, imgshape=img_shape
        )

        # read each frame and write it to the imgstore
        # unfortunately imgstore doesn't let us just add the file
        for i, img_filename in enumerate(filenames):
            img = cv2.imread(img_filename, flags=cv2.IMREAD_COLOR)
            store.add_image(img, i, i)

        store.close()

        # Return an ImgStoreVideo object referencing this new imgstore.
        return cls(backend=ImgStoreVideo(filename=output_filename))

    def to_imgstore(
        self,
        path: str,
        frame_numbers: List[int] = None,
        format: str = "png",
        index_by_original: bool = True,
    ) -> "Video":
        """
        Converts frames from arbitrary video backend to ImgStoreVideo.

        This should facilitate conversion of any video to a loopbio imgstore.

        Args:
            path: Filename or directory name to store imgstore.
            frame_numbers: A list of frame numbers from the video to save.
                If None save the entire video.
            format: By default it will create a DirectoryImgStore with lossless
                PNG format unless the frame_indices = None, in which case,
                it will default to 'mjpeg/avi' format for video.
            index_by_original: ImgStores are great for storing a collection of
                selected frames from an larger video. If the index_by_original
                is set to True then the get_frame function will accept the
                original frame numbers of from original video. If False,
                then it will accept the frame index from the store directly.
                Default to True so that we can use an ImgStoreVideo in a
                dataset to replace another video without having to update
                all the frame indices on :class:`LabeledFrame` objects in the dataset.

        Returns:
            A new Video object that references the imgstore.
        """

        # If the user has not provided a list of frames to store, store them all.
        if frame_numbers is None:
            frame_numbers = range(self.num_frames)

            # We probably don't want to store all the frames as the PNG default,
            # lets use MJPEG by default.
            format = "mjpeg/avi"

        # Delete the imgstore if it already exists.
        if os.path.exists(path):
            if os.path.isfile(path):
                os.remove(path)
            if os.path.isdir(path):
                shutil.rmtree(path, ignore_errors=True)

        # If the video is already an imgstore, we just need to copy it
        # if type(self) is ImgStoreVideo:
        #     new_backend = self.backend.copy_to(path)
        #     return self.__class__(backend=new_backend)

        store = imgstore.new_for_format(
            format,
            mode="w",
            basedir=path,
            imgshape=(self.height, self.width, self.channels),
            chunksize=1000,
        )

        # Write the JSON for the original video object to the metadata
        # of the imgstore for posterity
        store.add_extra_data(source_sleap_video_obj=Video.cattr().unstructure(self))

        import time

        for frame_num in frame_numbers:
            store.add_image(self.get_frame(frame_num), frame_num, time.time())

        # If there are no frames to save for this video, add a dummy frame
        # since we can't save an empty imgstore.
        if len(frame_numbers) == 0:
            store.add_image(
                np.zeros((self.height, self.width, self.channels)), 0, time.time()
            )

        store.close()

        # Return an ImgStoreVideo object referencing this new imgstore.
        return self.__class__(
            backend=ImgStoreVideo(filename=path, index_by_original=index_by_original)
        )

    def to_hdf5(
        self,
        path: str,
        dataset: str,
        frame_numbers: List[int] = None,
        format: str = "",
        index_by_original: bool = True,
    ):
        """
        Converts frames from arbitrary video backend to HDF5Video.

        Used for building an HDF5 that holds all data needed for training.

        Args:
            path: Filename to HDF5 (which could already exist).
            dataset: The HDF5 dataset in which to store video frames.
            frame_numbers: A list of frame numbers from the video to save.
                If None save the entire video.
            format: If non-empty, then encode images in format before saving.
                Otherwise, save numpy matrix of frames.
            index_by_original: If the index_by_original is set to True then
                the get_frame function will accept the original frame
                numbers of from original video.
                If False, then it will accept the frame index directly.
                Default to True so that we can use resulting video in a
                dataset to replace another video without having to update
                all the frame indices in the dataset.

        Returns:
            A new Video object that references the HDF5 dataset.
        """

        # If the user has not provided a list of frames to store, store them all.
        if frame_numbers is None:
            frame_numbers = range(self.num_frames)

        if frame_numbers:
            frame_data = self.get_frames(frame_numbers)
        else:
            frame_data = np.zeros((1, 1, 1, 1))

        frame_numbers_data = np.array(list(frame_numbers), dtype=int)

        with h5.File(path, "a") as f:

            if format:

                def encode(img):
                    _, encoded = cv2.imencode("." + format, img)
                    return np.squeeze(encoded)

                dtype = h5.special_dtype(vlen=np.dtype("int8"))
                dset = f.create_dataset(
                    dataset + "/video", (len(frame_numbers),), dtype=dtype
                )
                dset.attrs["format"] = format
                dset.attrs["channels"] = self.channels
                dset.attrs["height"] = self.height
                dset.attrs["width"] = self.width

                for i in range(len(frame_numbers)):
                    dset[i] = encode(frame_data[i])
            else:
                f.create_dataset(
                    dataset + "/video",
                    data=frame_data,
                    compression="gzip",
                    compression_opts=9,
                )

            if index_by_original:
                f.create_dataset(dataset + "/frame_numbers", data=frame_numbers_data)

        return self.__class__(
            backend=HDF5Video(
                filename=path,
                dataset=dataset + "/video",
                input_format="channels_last",
                convert_range=False,
            )
        )

    @staticmethod
    def cattr():
        """
        Returns a cattr converter for serialiazing/deserializing Video objects.

        Returns:
            A cattr converter.
        """

        # When we are structuring video backends, try to fixup the video file paths
        # in case they are coming from a different computer or the file has been moved.
        def fixup_video(x, cl):
            if "filename" in x:
                x["filename"] = Video.fixup_path(x["filename"])
            if "file" in x:
                x["file"] = Video.fixup_path(x["file"])

            return cl(**x)

        vid_cattr = cattr.Converter()

        # Check the type hint for backend and register the video path
        # fixup hook for each type in the Union.
        for t in attr.fields(Video).backend.type.__args__:
            vid_cattr.register_structure_hook(t, fixup_video)

        return vid_cattr

    @staticmethod
    def fixup_path(path: str, raise_error: bool = False) -> str:
        """
        Tries to locate video if the given path doesn't work.

        Given a path to a video try to find it. This is attempt to make the
        paths serialized for different video objects portable across multiple
        computers. The default behavior is to store whatever path is stored
        on the backend object. If this is an absolute path it is almost
        certainly wrong when transferred when the object is created on
        another computer. We try to find the video by looking in the current
        working directory as well.

        Note that when loading videos during the process of deserializing a
        saved :class:`Labels` dataset, it's usually preferable to fix video
        paths using a `video_callback`.

        Args:
            path: The path the video asset.
            raise_error: Whether to raise error if we cannot find video.

        Raises:
            FileNotFoundError: If file still cannot be found and raise_error
                is True.

        Returns:
            The fixed up path
        """

        # If path is not a string then just return it and assume the backend
        # knows what to do with it.
        if type(path) is not str:
            return path

        if os.path.exists(path):
            return path

        # Strip the directory and lets see if the file is in the current working
        # directory.
        elif os.path.exists(os.path.basename(path)):
            return os.path.basename(path)

        # Special case: this is an ImgStore path! We cant use
        # basename because it will strip the directory name off
        elif path.endswith("metadata.yaml"):

            # Get the parent dir of the YAML file.
            img_store_dir = os.path.basename(os.path.split(path)[0])

            if os.path.exists(img_store_dir):
                return img_store_dir

        if raise_error:
            raise FileNotFoundError(f"Cannot find a video file: {path}")
        else:
            logger.warning(f"Cannot find a video file: {path}")
            return path
