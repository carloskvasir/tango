from collections import OrderedDict
from typing import Dict, TypeVar

from tango.step import Step
from tango.step_info import StepInfo
from tango.workspace import Workspace
from tango.workspaces.remote_workspace import RemoteWorkspace

from .common import Constants, GCSStepLock, get_client
from .step_cache import GCSStepCache

T = TypeVar("T")


def dataset_url(workspace_url: str, dataset_name: str) -> str:
    # TODO: should be part of client.
    return workspace_url + "/ " + dataset_name


@Workspace.register("gs")
class GCSWorkspace(RemoteWorkspace):
    Constants = Constants

    def __init__(self, workspace: str, **kwargs):
        client = get_client(gcs_workspace=workspace, **kwargs)
        cache = GCSStepCache(workspace, client=client)
        locks: Dict[Step, GCSStepLock] = {}
        self._step_info_cache: "OrderedDict[str, StepInfo]" = OrderedDict()
        super().__init__(client, cache, "gs_workspace", locks)

    @property
    def url(self) -> str:
        return f"gs://{self.client.full_name}"

    def _remote_lock(self, step: Step) -> GCSStepLock:
        return GCSStepLock(self.client, step)

    @classmethod
    def _dataset_url(cls, workspace_url: str, dataset_name: str) -> str:
        return dataset_url(workspace_url, dataset_name)


# @Workspace.register("gs")
# class GCSWorkspace(Workspace):
#     """
#     This is a :class:`~tango.workspace.Workspace` that stores step artifacts on `Google Cloud Storage Buckets`_.
#
#     .. tip::
#         Registered as a :class:`~tango.workspace.Workspace` under the name "gs".
#
#     :param gcs_workspace: The name or ID of the Google Cloud Storage bucket to use.
#     :param kwargs: Additional keyword arguments passed to `GCSClient()`.
#     """
#
#     STEP_INFO_CACHE_SIZE = 512
#
#     def __init__(self, gcs_workspace: str, **kwargs):
#         super().__init__()
#         self.client = get_client(gcs_workspace=gcs_workspace, **kwargs)
#         self.cache = GCSStepCache(gcs_workspace, client=self.client)
#         self.steps_dir = tango_cache_dir() / "gs_workspace"
#         self.locks: Dict[Step, GCSStepLock] = {}
#         self._step_info_cache: "OrderedDict[str, StepInfo]" = OrderedDict()
#
#     @property
#     def url(self) -> str:
#         return f"gs://{self.client.full_name}"
#
#     @classmethod
#     def from_parsed_url(cls, parsed_url: ParseResult) -> Workspace:
#         workspace: str
#         if parsed_url.netloc and parsed_url.path:
#             # e.g. "gs://ai2/my-workspace"
#             # "Bucket names reside in a single namespace that is shared by all Cloud Storage users" from
#             # https://cloud.google.com/storage/docs/buckets. So, this should never happen.
#             workspace = parsed_url.netloc + parsed_url.path
#         elif parsed_url.netloc:
#             # e.g. "gs://my-workspace"
#             workspace = parsed_url.netloc
#         else:
#             raise ValueError(f"Bad URL for GCS workspace '{parsed_url}'")
#         return cls(workspace)
#
#     @property
#     def step_cache(self) -> StepCache:
#         return self.cache
#
#     def step_dir(self, step_or_unique_id: Union[Step, str]) -> Path:
#         unique_id = (
#             step_or_unique_id if isinstance(step_or_unique_id, str) else step_or_unique_id.unique_id
#         )
#         path = self.steps_dir / unique_id
#         path.mkdir(parents=True, exist_ok=True)
#         return path
#
#     def work_dir(self, step: Step) -> Path:
#         path = self.step_dir(step) / "work"
#         path.mkdir(parents=True, exist_ok=True)
#         return path
#
#     def step_info(self, step_or_unique_id: Union[Step, str]) -> StepInfo:
#         try:
#             dataset = self.client.get(Constants.step_dataset_name(step_or_unique_id))
#             file_info = self.client.file_info(dataset, Constants.STEP_INFO_FNAME)
#             step_info: StepInfo
#             if file_info.digest in self._step_info_cache:
#                 step_info = self._step_info_cache.pop(file_info.digest)
#             else:
#                 step_info_bytes = self.client.get_file(dataset, file_info)
#                 step_info = StepInfo.from_json_dict(json.loads(step_info_bytes))
#             self._step_info_cache[file_info.digest] = step_info
#             while len(self._step_info_cache) > self.STEP_INFO_CACHE_SIZE:
#                 self._step_info_cache.popitem(last=False)
#             return step_info
#         except (GCSDatasetNotFound, FileNotFoundError):
#             if not isinstance(step_or_unique_id, Step):
#                 raise KeyError(step_or_unique_id)
#             step_info = StepInfo.new_from_step(step_or_unique_id)
#             self._update_step_info(step_info)
#             return step_info
#
#     def step_starting(self, step: Step) -> None:
#         # We don't do anything with uncacheable steps.
#         if not step.cache_results:
#             return
#
#         # Get local file lock + remote GCS dataset lock.
#         lock = GCSStepLock(self.client, step)
#         lock.acquire()
#         self.locks[step] = lock
#
#         step_info = self.step_info(step)
#         if step_info.state == StepState.RUNNING:
#             # Since we've acquired the step lock we know this step can't be running
#             # elsewhere. But the step state can still say its running if the last
#             warnings.warn(
#                 f"Step info for step '{step.unique_id}' is invalid - says step is running "
#                 "although it shouldn't be. Ignoring and overwriting step start time.",
#                 UserWarning,
#             )
#         elif step_info.state not in {StepState.INCOMPLETE, StepState.FAILED, StepState.UNCACHEABLE}:
#             self.locks.pop(step).release()
#             raise StepStateError(
#                 step,
#                 step_info.state,
#                 context=f"If you are certain the step is not running somewhere else, delete the step "
#                 f"datasets at {dataset_url(self.client.url(), Constants.step_dataset_name(step))}",
#             )
#
#         if step_info.state == StepState.FAILED:
#             # Refresh the environment metadata since it might be out-of-date now.
#             step_info.refresh()
#
#         # Update StepInfo to mark as running.
#         try:
#             step_info.start_time = utc_now_datetime()
#             step_info.end_time = None
#             step_info.error = None
#             step_info.result_location = None
#             self._update_step_info(step_info)
#         except:  # noqa: E722
#             self.locks.pop(step).release()
#             raise
#
#     def step_finished(self, step: Step, result: T) -> T:
#         # We don't do anything with uncacheable steps.
#         if not step.cache_results:
#             return result
#
#         step_info = self.step_info(step)
#         if step_info.state != StepState.RUNNING:
#             raise StepStateError(step, step_info.state)
#
#         # Update step info and save step execution metadata.
#         # This needs to be done *before* adding the result to the cache, since adding
#         # the result to the cache will commit the step dataset, making it immutable.
#         step_info.end_time = utc_now_datetime()
#         step_info.result_location = self.client.url(Constants.step_dataset_name(step))
#         self._update_step_info(step_info)
#
#         self.cache[step] = result
#         if hasattr(result, "__next__"):
#             assert isinstance(result, Iterator)
#             # Caching the iterator will consume it, so we write it to the cache and then read from the cache
#             # for the return value.
#             result = self.cache[step]
#
#         self.locks.pop(step).release()
#
#         return result
#
#     def step_failed(self, step: Step, e: BaseException) -> None:
#         # We don't do anything with uncacheable steps.
#         if not step.cache_results:
#             return
#
#         try:
#             step_info = self.step_info(step)
#             if step_info.state != StepState.RUNNING:
#                 raise StepStateError(step, step_info.state)
#             step_info.end_time = utc_now_datetime()
#             step_info.error = exception_to_string(e)
#             self._update_step_info(step_info)
#         finally:
#             self.locks.pop(step).release()
#
#     def register_run(self, targets: Iterable[Step], name: Optional[str] = None) -> Run:
#         import concurrent.futures
#
#         all_steps = set(targets)
#         for step in targets:
#             all_steps |= step.recursive_dependencies
#
#         # Create a GCS dataset that represents this run. The dataset which just contain
#         # a JSON file that maps step names to step unique IDs.
#         run_dataset: GCSDataset
#         if name is None:
#             # Find a unique name to use.
#             while True:
#                 name = petname.generate() + str(random.randint(0, 100))
#                 try:
#                     run_dataset = self.client.create(
#                         Constants.run_dataset_name(cast(str, name)), commit=False
#                     )
#                 except GCSDatasetConflict:
#                     continue
#                 else:
#                     break
#         else:
#             try:
#                 run_dataset = self.client.create(Constants.run_dataset_name(name), commit=False)
#             except GCSDatasetConflict:
#                 raise ValueError(f"Run name '{name}' is already in use")
#
#         steps: Dict[str, StepInfo] = {}
#         run_data: Dict[str, str] = {}
#
#         # Collect step info.
#         with concurrent.futures.ThreadPoolExecutor(
#             thread_name_prefix="GCSWorkspace.register_run()-"
#         ) as executor:
#             step_info_futures = []
#             for step in all_steps:
#                 if step.name is None:
#                     continue
#                 step_info_futures.append(executor.submit(self.step_info, step))
#             for future in concurrent.futures.as_completed(step_info_futures):
#                 step_info = future.result()
#                 assert step_info.step_name is not None
#                 steps[step_info.step_name] = step_info
#                 run_data[step_info.step_name] = step_info.unique_id
#
#         # Upload run data to dataset.
#         # NOTE: We don't commit the dataset here since we'll need to upload the logs file
#         # after the run.
#         self.client.upload(run_dataset, json.dumps(run_data).encode(), Constants.RUN_DATA_FNAME)
#
#         return Run(name=cast(str, name), steps=steps, start_date=run_dataset.created)
#
#     def registered_runs(self) -> Dict[str, Run]:
#         import concurrent.futures
#
#         runs: Dict[str, Run] = {}
#
#         with concurrent.futures.ThreadPoolExecutor(
#             max_workers=9, thread_name_prefix="GCSWorkspace.registered_runs()-"
#         ) as executor:
#             run_futures = []
#             for dataset in self.client.datasets(
#                 match=Constants.RUN_DATASET_PREFIX, results=False  # TODO: results?
#             ):
#                 run_futures.append(executor.submit(self._get_run_from_dataset, dataset))
#             for future in concurrent.futures.as_completed(run_futures):
#                 run = future.result()
#                 if run is not None:
#                     runs[run.name] = run
#
#         return runs
#
#     def registered_run(self, name: str) -> Run:
#         err_msg = f"Run '{name}' not found in workspace"
#
#         try:
#             dataset_for_run = self.client.get(Constants.run_dataset_name(name))
#             # TODO: what's this check? seems to be beaker specific.
#             # # Make sure the run is in our workspace.
#             # if dataset_for_run.workspace_ref.id != self.beaker.workspace.get().id:
#             #     raise DatasetNotFound
#         except GCSDatasetNotFound:
#             raise KeyError(err_msg)
#
#         run = self._get_run_from_dataset(dataset_for_run)
#         if run is None:
#             raise KeyError(err_msg)
#         else:
#             return run
#
#     @contextmanager
#     def capture_logs_for_run(self, name: str) -> Generator[None, None, None]:
#         with tempfile.TemporaryDirectory() as tmp_dir_name:
#             log_file = Path(tmp_dir_name) / "out.log"
#             try:
#                 with file_handler(log_file):
#                     yield None
#             finally:
#                 run_dataset = Constants.run_dataset_name(name)
#                 self.client.sync(run_dataset, log_file)
#                 # TODO: what should commit do?
#                 # self.client.commit(run_dataset)
#
#     def _get_run_from_dataset(self, dataset: GCSDataset) -> Optional[Run]:
#         if dataset.name is None:
#             return None
#         if not dataset.name.startswith(Constants.RUN_DATASET_PREFIX):
#             return None
#
#         try:
#             run_name = dataset.name[len(Constants.RUN_DATASET_PREFIX) :]
#             steps: Dict[str, StepInfo] = {}
#             steps_info_bytes = self.client.get_file(dataset, Constants.RUN_DATA_FNAME)
#             steps_info = json.loads(steps_info_bytes)
#         except (GCSDatasetNotFound, FileNotFoundError):
#             return None
#
#         import concurrent.futures
#
#         with concurrent.futures.ThreadPoolExecutor(
#             max_workers=9, thread_name_prefix="GCSWorkspace._get_run_from_dataset()-"
#         ) as executor:
#             step_info_futures = []
#             for unique_id in steps_info.values():
#                 step_info_futures.append(executor.submit(self.step_info, unique_id))
#             for future in concurrent.futures.as_completed(step_info_futures):
#                 step_info = future.result()
#                 assert step_info.step_name is not None
#                 steps[step_info.step_name] = step_info
#
#         return Run(name=run_name, start_date=dataset.created, steps=steps)
#
#     def _update_step_info(self, step_info: StepInfo):
#         dataset_name = Constants.step_dataset_name(step_info)
#
#         step_info_dataset: GCSDataset
#         try:
#             # TODO: commit doesnt do anything here
#             step_info_dataset = self.client.create(dataset_name, commit=False)
#         except GCSDatasetConflict:
#             step_info_dataset = self.client.get(dataset_name)
#
#         self.client.upload(
#             step_info_dataset,  # folder name
#             json.dumps(step_info.to_json_dict()).encode(),  # step info dict.
#             Constants.STEP_INFO_FNAME,  # step info filename
#         )
