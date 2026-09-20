"""
Seeds the database with problems derived directly from your original
evaluation_script.py test_suite, now expanded with the fields the real
schema needs (tests, reference_solution, bug_category -- none of which
existed in the old script, since it never executed code).

Run with: python -m database.seed
"""

from database.db import SessionLocal, Base, engine
from models import Problem

PROBLEMS = [
    dict(
        title="Filter Large Numbers",
        description="Write a function that returns only the numbers greater than 10 from a list.",
        difficulty="easy",
        concept="conditionals",
        bug_category="incorrect_comparison_operator",
        language="python",
        starter_code=(
            "def get_large_numbers(numbers):\n"
            "    large_numbers = []\n"
            "    for num in numbers:\n"
            "        if num < 10:\n"
            "            large_numbers.append(num)\n"
            "    return large_numbers\n"
        ),
        reference_solution=(
            "def get_large_numbers(numbers):\n"
            "    large_numbers = []\n"
            "    for num in numbers:\n"
            "        if num > 10:\n"
            "            large_numbers.append(num)\n"
            "    return large_numbers\n"
        ),
        # NOTE: these test harnesses assume the student's submitted code is
        # followed by a driver that prints the result -- in the real
        # implementation, wrap `submitted_code` with a small harness before
        # execution (call the function with the test's input, print() the
        # return value) rather than relying on the student's code to print
        # anything itself. Sketched here as plain stdin/expected_stdout
        # pairs for a harness that does `print(get_large_numbers({stdin}))`.
        tests={
            "visible": [{"id": "visible_1", "stdin": "[5, 12, 8, 20]", "expected_stdout": "[12, 20]"}],
            "hidden": [{"id": "hidden_1", "stdin": "[1, 2, 3]", "expected_stdout": "[]"}],
        },
    ),
    dict(
        title="Double Every Value",
        description="Write a function that doubles every number in a list, in place.",
        difficulty="easy",
        concept="loops_and_indexing",
        bug_category="off_by_one_index_error",
        language="python",
        starter_code=(
            "def double_values(numbers):\n"
            "    for i in range(len(numbers) + 1):\n"
            "        numbers[i] = numbers[i] * 2\n"
            "    return numbers\n"
        ),
        reference_solution=(
            "def double_values(numbers):\n"
            "    for i in range(len(numbers)):\n"
            "        numbers[i] = numbers[i] * 2\n"
            "    return numbers\n"
        ),
        tests={
            "visible": [{"id": "visible_1", "stdin": "[1, 2, 3, 4]", "expected_stdout": "[2, 4, 6, 8]"}],
            "hidden": [{"id": "hidden_1", "stdin": "[10]", "expected_stdout": "[20]"}],
        },
    ),
    dict(
        title="Remove Odd Numbers",
        description="Write a function that removes all odd numbers from a list.",
        difficulty="medium",
        concept="list_mutation",
        bug_category="mutation_while_iterating",
        language="python",
        starter_code=(
            "def remove_odd_numbers(numbers):\n"
            "    for num in numbers:\n"
            "        if num % 2 != 0:\n"
            "            numbers.remove(num)\n"
            "    return numbers\n"
        ),
        reference_solution=(
            "def remove_odd_numbers(numbers):\n"
            "    return [num for num in numbers if num % 2 == 0]\n"
        ),
        tests={
            "visible": [{"id": "visible_1", "stdin": "[1, 2, 3, 4, 5]", "expected_stdout": "[2, 4]"}],
            "hidden": [{"id": "hidden_1", "stdin": "[7, 9]", "expected_stdout": "[]"}],
        },
    ),
    dict(
        title="Fix the Student Record",
        description="This dictionary literal has a syntax problem -- find and fix it.",
        difficulty="easy",
        concept="syntax",
        bug_category="missing_punctuation",
        language="python",
        starter_code=(
            'student_data = {\n'
            '    "name": "Alex",\n'
            '    "age": 20\n'
            '    "major": "Computer Science"\n'
            '}\n'
        ),
        reference_solution=(
            'student_data = {\n'
            '    "name": "Alex",\n'
            '    "age": 20,\n'
            '    "major": "Computer Science"\n'
            '}\n'
        ),
        tests={
            "visible": [{"id": "visible_1", "stdin": "", "expected_stdout": ""}],
            "hidden": [],
        },
    ),
    dict(
        title="Rectangle Area",
        description="Write a function that calculates the area of a rectangle.",
        difficulty="easy",
        concept="control_case",
        bug_category="none",
        language="python",
        starter_code=(
            "def calculate_area(length, width):\n"
            "    if length <= 0 or width <= 0:\n"
            "        return 0\n"
            "    return length * width\n"
        ),
        reference_solution=(
            "def calculate_area(length, width):\n"
            "    if length <= 0 or width <= 0:\n"
            "        return 0\n"
            "    return length * width\n"
        ),
        tests={
            "visible": [{"id": "visible_1", "stdin": "3 4", "expected_stdout": "12"}],
            "hidden": [{"id": "hidden_1", "stdin": "-1 5", "expected_stdout": "0"}],
        },
    ),
]


def seed():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        if db.query(Problem).count() > 0:
            print("Problems already seeded, skipping.")
            return
        for p in PROBLEMS:
            db.add(Problem(**p))
        db.commit()
        print(f"Seeded {len(PROBLEMS)} problems.")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
