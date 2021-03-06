"""Serializable configuration classes for specifying all training job parameters.

These configuration classes are intended to specify all the parameters required to run
a training job or perform inference from a serialized one.

They are explicitly not intended to implement any of the underlying functionality that
they parametrize. This serves two purposes:

    1. Parameter specification through simple attributes. These can be read/edited by a
        human, as well as easily be serialized/deserialized to/from simple dictionaries
        and JSON.

    2. Decoupling from the implementation. This makes it easier to design functional
        modules with attributes/parameters that contain objects that may not be easily
        serializable or may implement additional logic that relies on runtime
        information or other parameters.

In general, classes that implement the actual functionality related to these
configuration classes should provide a classmethod for instantiation from the
configuration class instances. This makes it easier to implement other logic not related
to the high level parameters at creation time.

Conveniently, this format also provides a single location where all user-facing
parameters are aggregated and documented for end users (as opposed to developers).
"""

import os
import attr
import cattr
import sleap
from sleap.nn.config.data import DataConfig
from sleap.nn.config.model import ModelConfig
from sleap.nn.config.optimization import OptimizationConfig
from sleap.nn.config.outputs import OutputsConfig
import json
from jsmin import jsmin
from typing import Text, Dict, Any, Optional


@attr.s(auto_attribs=True)
class TrainingJobConfig:
    """Configuration of a training job.

    Attributes:
        data: Configuration options related to the training data.
        model: Configuration options related to the model architecture.
        optimization: Configuration options related to the training.
        outputs: Configuration options related to outputs during training.
        name: Optional name for this configuration profile.
        description: Optional description of the configuration.
        sleap_version: Version of SLEAP that generated this configuration.
        filename: Path to this config file if it was loaded from disk.
    """

    data: DataConfig = attr.ib(factory=DataConfig)
    model: ModelConfig = attr.ib(factory=ModelConfig)
    optimization: OptimizationConfig = attr.ib(factory=OptimizationConfig)
    outputs: OutputsConfig = attr.ib(factory=OutputsConfig)
    name: Optional[Text] = ""
    description: Optional[Text] = ""
    sleap_version: Optional[Text] = sleap.__version__
    filename: Optional[Text] = ""

    @classmethod
    def from_json_dicts(cls, json_data_dicts: Dict[Text, Any]) -> "TrainingJobConfig":
        """Create training job configuration from dictionaries decoded from JSON.

        Arguments:
            json_data_dicts: Dictionaries that specify the configurations. These are
                typically generated by structuring raw JSON formatted text.

        Returns:
            A TrainingJobConfig instance parsed from the JSON dicts.
        """
        # TODO: Detect and parse legacy training job format.
        return cattr.structure(json_data_dicts, cls)

    @classmethod
    def from_json(cls, json_data: Text) -> "TrainingJobConfig":
        """Create training job configuration from JSON text data.

        Arguments:
            json_data: JSON-formatted string that specifies the configurations.

        Returns:
            A TrainingJobConfig instance parsed from the JSON text.
        """
        # Open and parse the JSON data into dictionaries.
        json_data_dicts = json.loads(jsmin(json_data))
        return cls.from_json_dicts(json_data_dicts)

    @classmethod
    def load_json(
        cls, filename: Text, load_training_config: bool = True
    ) -> "TrainingJobConfig":
        """Load a training job configuration from a file.

        Arguments:
            filename: Path to a training job configuration JSON file or a directory
                containing `"training_job.json"`.
            load_training_config: If `True` (the default), prefer `training_job.json`
                over `initial_config.json` if it is present in the same folder.

        Returns:
          A TrainingJobConfig instance parsed from the file.
        """
        if load_training_config and filename.endswith("initial_config.json"):
            training_config_path = os.path.join(
                os.path.dirname(filename), "training_config.json"
            )
            if os.path.exists(training_config_path):
                filename = training_config_path

        # Use stored configuration if a directory was provided.
        if os.path.isdir(filename):
            filename = os.path.join(filename, "training_config.json")

        # Open and read the JSON data.
        with open(filename, "r") as f:
            json_data = f.read()

        obj = cls.from_json(json_data)
        obj.filename = filename
        return obj

    def to_json(self) -> str:
        """Serialize the configuration into JSON-encoded string format.

        Returns:
            The JSON encoded string representation of the configuration.
        """
        json_dicts = cattr.unstructure(self)
        return json.dumps(json_dicts, indent=4)

    def save_json(self, filename: Text):
        """Save the configuration to a JSON file.

        Arguments:
            filename: Path to save the training job file to.
        """
        self.filename = filename
        with open(filename, "w") as f:
            f.write(self.to_json())


def load_config(filename: Text, load_training_config: bool = True) -> TrainingJobConfig:
    """Load a training job configuration for a model run.

    Args:
        filename: Path to a JSON file or directory containing `training_job.json`.
        load_training_config: If `True` (the default), prefer `training_job.json` over
            `initial_config.json` if it is present in the same folder.

    Returns:
        The parsed `TrainingJobConfig`.
    """
    return TrainingJobConfig.load_json(
        filename, load_training_config=load_training_config
    )
