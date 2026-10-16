
from datetime import date


def normalize(value: str | None) -> str:
    """Normalize text before comparing attributes."""
    return " ".join((value or "").lower().split())


# --------------------------------------------------
# 1. FORWARD CHAINING
# --------------------------------------------------

FORWARD_RULES = [
    {
        "conditions": ["category_match"],
        "conclusion": "same_category",
    },
    {
        "conditions": ["color_match"],
        "conclusion": "color_supported",
    },
    {
        "conditions": ["date_close", "location_supported"],
        "conclusion": "context_supported",
    },
    {
        "conditions": ["same_category", "text_similar"],
        "conclusion": "plausible_match",
    },
    {
        "conditions": [
            "same_category",
            "color_supported",
            "context_supported",
        ],
        "conclusion": "plausible_match",
    },
]


def forward_chaining(initial_facts: set[str]) -> set[str]:
    """
    Start with known facts and repeatedly apply rules
    until no additional facts can be derived.
    """
    facts = set(initial_facts)

    changed = True

    while changed:
        changed = False

        for rule in FORWARD_RULES:
            if all(
                condition in facts
                for condition in rule["conditions"]
            ):
                conclusion = rule["conclusion"]

                if conclusion not in facts:
                    facts.add(conclusion)
                    changed = True

    return facts


# --------------------------------------------------
# 2. BACKWARD CHAINING
# --------------------------------------------------

BACKWARD_RULES = {
    "same_category": [
        ["category_match"],
    ],
    "color_supported": [
        ["color_match"],
    ],
    "context_supported": [
        ["date_close", "location_supported"],
    ],
    "plausible_match": [
        ["same_category", "text_similar"],
        [
            "same_category",
            "color_supported",
            "context_supported",
        ],
    ],
}


def backward_chaining(
    goal: str,
    known_facts: set[str],
) -> bool:
    """
    Start with a goal and recursively check whether
    known facts and rules can establish that goal.
    """
    def prove(
        current_goal: str,
        active_goals: set[str],
    ) -> bool:
        if current_goal in known_facts:
            return True

        # Prevent infinite recursion if rules contain cycles.
        if current_goal in active_goals:
            return False

        alternatives = BACKWARD_RULES.get(
            current_goal, []
        )

        next_active = active_goals | {current_goal}

        # Each alternative is an AND of required conditions.
        # Different alternatives represent OR.
        for conditions in alternatives:
            if all(
                prove(condition, next_active)
                for condition in conditions
            ):
                return True

        return False

    return prove(goal, set())


# --------------------------------------------------
# 3. BACKTRACKING
# --------------------------------------------------


def find_evidence_combination(
    evidence: list[str],
    required_count: int = 2,
    target_goal: str = "plausible_match",
) -> list[str] | None:
    """
    Find the smallest combination of evidence that supports a goal.

    Backtracking explores combinations by including or skipping
    evidence. A combination is accepted only if forward chaining
    can derive the requested goal from it.
    """

    if required_count < 1:
        raise ValueError("required_count must be at least 1.")

    # Remove duplicate evidence while preserving its order.
    evidence = list(dict.fromkeys(evidence))

    if required_count > len(evidence):
        return None

    # Try smaller combinations before larger ones.
    for target_size in range(required_count, len(evidence) + 1):

        selected: list[str] = []

        def search(index: int) -> list[str] | None:
            # A complete combination has been selected.
            if len(selected) == target_size:
                derived = forward_chaining(set(selected))

                if target_goal in derived:
                    return selected.copy()

                return None

            # No evidence remains to fill the combination.
            if index >= len(evidence):
                return None

            # Prune branches that cannot reach the target size.
            remaining_slots = target_size - len(selected)

            if len(evidence) - index < remaining_slots:
                return None

            # Branch 1: include the current evidence.
            selected.append(evidence[index])

            result = search(index + 1)

            if result is not None:
                return result

            # Backtrack: undo the choice.
            selected.pop()

            # Branch 2: skip the current evidence.
            return search(index + 1)

        result = search(0)

        if result is not None:
            return result

    return None




# --------------------------------------------------
# BUILD FACTS FROM A REPORT PAIR
# --------------------------------------------------

def build_match_facts(
    lost,
    found,
    components: dict[str, float],
) -> set[str]:
    """Convert report attributes and similarity scores into facts."""
    facts = set()

    if normalize(lost.category) == normalize(found.category):
        facts.add("category_match")

    lost_color = normalize(lost.color)
    found_color = normalize(found.color)

    if lost_color and found_color and lost_color == found_color:
        facts.add("color_match")

    date_gap = abs(
        (lost.event_date - found.event_date).days
    )

    if date_gap <= 7:
        facts.add("date_close")

    # The existing location score is in the range [0, 1].
    # Missing coordinates produce 0 in the current implementation,
    # so don't treat that as evidence of a distant location.
    if (
        lost.latitude is not None
        and lost.longitude is not None
        and found.latitude is not None
        and found.longitude is not None
        and components.get("location", 0.0) >= 0.5
    ):
        facts.add("location_supported")

    if components.get("text", 0.0) >= 0.65:
        facts.add("text_similar")

    return facts


# --------------------------------------------------
# COMBINE ALL THREE TECHNIQUES
# --------------------------------------------------


def evaluate_match(
    lost,
    found,
    components: dict[str, float],
) -> dict:
    """Evaluate one lost/found pair using all three algorithms."""

    initial_facts = build_match_facts(
        lost,
        found,
        components,
    )

    # Technique 1: derive facts from the available evidence.
    derived_facts = forward_chaining(initial_facts)

    # Technique 2: check whether the goal can be proved
    # directly from the initial facts and backward rules.
    goal_proven = backward_chaining(
        "plausible_match",
        initial_facts,
    )

    # Technique 3: find the smallest evidence combination
    # that can derive the same goal.
    evidence_options = [
        fact
        for fact in (
            "category_match",
            "color_match",
            "date_close",
            "location_supported",
            "text_similar",
        )
        if fact in initial_facts
    ]

    combination = find_evidence_combination(
        evidence=evidence_options,
        required_count=2,
        target_goal="plausible_match",
    )

    return {
        "plausible_match": (
            "plausible_match" in derived_facts
            and goal_proven
        ),
        "forward_chaining_facts": sorted(derived_facts),
        "backward_chaining_goal_proven": goal_proven,
        "backtracking_evidence": combination,
    }
