"""Tests for task dependency graph (dependencies.py)."""

from code_muse.plugins.task_context.dependencies import (
    find_overlapping_tasks,
    get_all_dependency_edges,
    get_task_files,
    record_file_access,
    sync_cross_references,
)
from code_muse.plugins.task_context.dependencies import (
    reset as reset_deps,
)


class TestRecordFileAccess:
    def test_record_single_file(self):
        reset_deps()
        record_file_access("task-a", ["src/main.py"])
        assert get_task_files("task-a") == {"src/main.py"}

    def test_record_multiple_files(self):
        reset_deps()
        record_file_access("task-a", ["src/main.py", "src/utils.py"])
        assert get_task_files("task-a") == {"src/main.py", "src/utils.py"}

    def test_record_additive(self):
        reset_deps()
        record_file_access("task-a", ["f1.py"])
        record_file_access("task-a", ["f2.py"])
        assert get_task_files("task-a") == {"f1.py", "f2.py"}

    def test_unknown_task_returns_empty(self):
        reset_deps()
        assert get_task_files("ghost") == set()


class TestFindOverlappingTasks:
    def test_basic_overlap(self):
        reset_deps()
        record_file_access("task-a", ["src/main.py", "src/utils.py", "src/config.py"])
        record_file_access("task-b", ["src/main.py", "src/utils.py", "src/db.py"])
        overlaps = find_overlapping_tasks("task-a", min_overlap=2)
        assert len(overlaps) == 1
        assert overlaps[0][0] == "task-b"
        assert overlaps[0][1] == 2  # Two shared files

    def test_no_overlap_below_threshold(self):
        reset_deps()
        record_file_access("task-a", ["src/main.py", "src/utils.py"])
        record_file_access("task-b", ["src/main.py"])  # Only 1 shared
        overlaps = find_overlapping_tasks("task-a", min_overlap=2)
        assert len(overlaps) == 0

    def test_multiple_overlaps(self):
        reset_deps()
        record_file_access("task-a", ["f1.py", "f2.py", "f3.py"])
        record_file_access("task-b", ["f1.py", "f2.py", "f4.py"])
        record_file_access("task-c", ["f1.py", "f2.py", "f5.py"])
        overlaps = find_overlapping_tasks("task-a")
        assert len(overlaps) == 2

    def test_sorted_by_overlap_count(self):
        reset_deps()
        record_file_access("task-a", ["f1.py", "f2.py", "f3.py", "f4.py"])
        record_file_access("task-b", ["f1.py", "f2.py"])  # 2 overlap
        record_file_access("task-c", ["f1.py", "f2.py", "f3.py"])  # 3 overlap
        overlaps = find_overlapping_tasks("task-a")
        assert overlaps[0][0] == "task-c"
        assert overlaps[0][1] == 3

    def test_empty_task_files(self):
        reset_deps()
        overlaps = find_overlapping_tasks("nonexistent")
        assert overlaps == []

    def test_self_excluded(self):
        reset_deps()
        record_file_access("task-a", ["f1.py", "f2.py"])
        overlaps = find_overlapping_tasks("task-a")
        assert all(tid != "task-a" for tid, _ in overlaps)


class TestGetAllDependencyEdges:
    def test_basic_edges(self):
        reset_deps()
        record_file_access("a", ["x.py", "y.py"])
        record_file_access("b", ["x.py", "y.py", "z.py"])
        edges = get_all_dependency_edges()
        assert len(edges) >= 1
        # Edge should show overlap count
        assert edges[0][2] >= 2

    def test_no_edges_below_threshold(self):
        reset_deps()
        record_file_access("a", ["x.py"])
        record_file_access("b", ["x.py"])  # Only 1 shared
        edges = get_all_dependency_edges()
        assert len(edges) == 0

    def test_deduplication(self):
        reset_deps()
        record_file_access("a", ["x.py", "y.py"])
        record_file_access("b", ["x.py", "y.py"])
        edges = get_all_dependency_edges()
        # Should only have one edge (a, b) not (b, a)
        assert len(edges) == 1


class TestSyncCrossReferences:
    def test_auto_populates_cross_refs(self):
        from code_muse.plugins.task_context.task_manager import TaskManager

        reset_deps()
        mgr = TaskManager()
        t1 = mgr.get_active_task_id()
        t2 = mgr.start_new_task(label="second")
        record_file_access(t1, ["f1.py", "f2.py", "f3.py"])
        record_file_access(t2, ["f1.py", "f2.py", "f4.py"])

        added = sync_cross_references(mgr, min_overlap=2)
        assert added >= 1
        task1 = mgr.get_task(t1)
        assert t2 in task1.cross_referenced_task_ids

    def test_no_duplicate_cross_refs(self):
        from code_muse.plugins.task_context.task_manager import TaskManager

        reset_deps()
        mgr = TaskManager()
        t1 = mgr.get_active_task_id()
        t2 = mgr.start_new_task(label="second")
        record_file_access(t1, ["f1.py", "f2.py"])
        record_file_access(t2, ["f1.py", "f2.py"])

        added1 = sync_cross_references(mgr, min_overlap=2)
        added2 = sync_cross_references(mgr, min_overlap=2)
        assert added1 >= 1
        assert added2 == 0  # Already linked
