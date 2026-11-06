"""Original exercise text; names and further reading credit Bo Bennett's library.

No reference-site examples or descriptive prose are reproduced.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Fallacy:
    name: str
    slug: str
    aliases: tuple[str, ...]
    example: str
    explanation: str
    repair: str
    hint: str

    @property
    def reference(self):
        return "https://www.logicallyfallacious.com/logicalfallacies/" + self.slug


LIBRARY = (
    Fallacy(
        "Ad hominem",
        "Ad-Hominem-Abusive",
        ("personal attack", "abusive ad hominem"),
        "Mira's proposal about {topic} can be dismissed because she is an unpleasant person.",
        "The speaker substitutes an irrelevant personal insult for examining the evidence.",
        "Evaluate Mira's proposal using its costs and likely effects, regardless of her"
        " personality.",
        "What work does the comment about Mira do in the argument?",
    ),
    Fallacy(
        "Straw man",
        "Strawman-Fallacy",
        ("strawman", "misrepresentation"),
        "Leo suggests a small trial about {topic}. His plan would force everyone to"
        " participate forever, so reject it.",
        "A limited trial is replaced with a much stronger compulsory policy, which is"
        " then attacked.",
        "Evaluate the actual proposal and its stated scope before objecting to its consequences.",
        "Compare the proposal with the version being criticized.",
    ),
    Fallacy(
        "False dilemma",
        "False-Dilemma",
        ("false dichotomy", "either or", "black or white"),
        "Regarding {topic}, either approve my entire plan today or admit that you oppose"
        " all progress.",
        "The argument excludes alternatives such as a partial plan, revision or a later decision.",
        "Compare this plan, narrower alternatives and a later decision against the same goals.",
        "Are the offered choices exhaustive?",
    ),
    Fallacy(
        "Begging the question",
        "Begging-the-Question",
        ("circular reasoning", "circular argument"),
        "My rule for {topic} is fair because it is the rule that treats people fairly.",
        "The premise repeats the conclusion instead of giving independent grounds "
        "for accepting it.",
        "Explain an independent standard and show how the rule satisfies it in concrete cases.",
        "Does the reason give information independent of the conclusion?",
    ),
    Fallacy(
        "Hasty generalization",
        "Hasty-Generalization",
        ("small sample", "overgeneralization"),
        "Two people in my club dislike {topic}, so everyone in the city must dislike it.",
        "A tiny, selected sample is used to make a claim about a much larger population.",
        "Limit the conclusion to those two people or obtain a representative city-wide sample.",
        "Who was sampled, and whom does the conclusion describe?",
    ),
    Fallacy(
        "Slippery slope",
        "Slippery-Slope",
        ("domino fallacy", "unsupported chain"),
        "Allow one optional workshop about {topic} and soon every class will be"
        " cancelled and nobody will learn anything.",
        "A chain ending in disaster is asserted without evidence connecting its"
        " intermediate steps.",
        "Evaluate the workshop directly and investigate any specific, plausible"
        " scheduling effects.",
        "Which steps in the predicted chain have actually been justified?",
    ),
    Fallacy(
        "Cherry picking",
        "Cherry-Picking",
        ("selective evidence", "suppressed evidence"),
        "Of twenty evaluations of {topic}, nineteen found no benefit. I will cite only"
        " the one positive evaluation to prove it works.",
        "The speaker deliberately selects a favorable observation while excluding"
        " relevant contrary results.",
        "Report all relevant observations and examine their methods before drawing a conclusion.",
        "Which available observations are missing from the stated evidence?",
    ),
    Fallacy(
        "Shifting the burden of proof",
        "Shifting-of-the-Burden-of-Proof",
        ("burden of proof", "appeal to ignorance"),
        "My new device solves every problem in {topic}; unless you disprove that, you"
        " must accept my claim.",
        "The claimant demands disproof instead of supporting the broad positive claim.",
        "Supply reproducible tests of specified capabilities and limit the claim to what"
        " they show.",
        "Who is making the claim, and who is being asked to establish it?",
    ),
    Fallacy(
        "Red herring",
        "Red-Herring",
        ("irrelevant diversion", "distraction"),
        "You asked whether the {topic} project met its budget. Let us talk instead about"
        " how attractive its logo is.",
        "The response diverts attention to an unrelated aesthetic question without"
        " addressing the budget.",
        "Answer the requested question using relevant records; discuss the other issue separately.",
        "Does the response address the actual question?",
    ),
    Fallacy(
        "Appeal to popularity",
        "Appeal-to-Popularity",
        ("bandwagon", "ad populum"),
        "Most people in our chat believe this claim about {topic}, so the claim must be"
        " factually true.",
        "The number of believers is substituted for evidence about the factual proposition.",
        "Check evidence for the claim while reporting the poll only as an observation"
        " about opinion.",
        "Does agreement establish the underlying fact?",
    ),
)


def find_fallacy(name):
    normalized = name.casefold().replace("-", " ").strip()
    for entry in LIBRARY:
        if normalized in {entry.name.casefold(), *(alias.casefold() for alias in entry.aliases)}:
            return entry
    return None


# A second original scenario per family prevents focused practice repeating one sentence.
VARIANTS = {
    "Ad hominem": "Niko's evidence about {topic} must be wrong because Niko dresses badly.",
    "Straw man": "Asha asks for clearer reporting on {topic}. So Asha wants to shut the"
    " whole project down; we cannot accept that.",
    "False dilemma": "Either our club spends every cent on {topic}, or the club cares"
    " nothing about the future.",
    "Begging the question": "This guideline for {topic} is the correct one, because it"
    " is the guideline we ought to follow.",
    "Hasty generalization": "I saw one unsuccessful {topic} project, which proves every"
    " project of that kind fails.",
    "Slippery slope": "If we postpone one {topic} meeting, soon nobody will attend any"
    " meeting and the organization will collapse.",
    "Cherry picking": "Our survey on {topic} had ten negative answers and one positive"
    " answer. Show only the positive answer as proof of success.",
    "Shifting the burden of proof": "My secret method for {topic} is flawless. You must"
    " prove a flaw before I need to show how it works.",
    "Red herring": "The committee asks whether the {topic} trial delivered its promised"
    " results. I reply that our office has excellent furniture.",
    "Appeal to popularity": "The most shared post about {topic} says the number doubled,"
    " so that measurement must be accurate.",
}
