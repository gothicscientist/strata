"""The curated Strata reference panel.

These are AADR ``Group ID`` labels. They are matched against the ``.anno`` file
with the rules in :func:`resolve`: a label may be given exactly, or as a prefix
pattern ending in ``*`` when AADR splits one archaeological group across
several suffixed labels (e.g. per-period or per-site variants).

Why these groups: the panel is built to support South Asian ancestry questions,
which in the published literature are modelled as mixtures of three deep
components — an Iranian-plateau-related (Iran_N / Ganj Dareh-like) component,
an Ancient Ancestral South Indian (AASI) component for which the Andamanese
(Onge) are the usual imperfect proxy, and a Steppe Middle/Late Bronze Age
component — assembled through the Indus-periphery cline. The ancient groups
below are the ones those models are built from; the right (outgroup) set is the
standard deep-outgroup set used with them; and the modern groups span the
"Indian cline" so a user's own coordinates can be placed against it.

A label present here but absent from a given AADR release is reported, not
fatal: AADR renames groups between versions, and the build must not stop
because one label moved.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# --------------------------------------------------------------------------
# right / outgroup set
# --------------------------------------------------------------------------

# The conventional deep outgroup set for South/Central Asian qpAdm. Right
# populations must be outgroups to the admixture event being tested; these are
# deep enough to be unaffected by it while still being informative.
BASE_RIGHT: tuple[str, ...] = (
    "Mbuti.DG",
    "Ust_Ishim_published.DG",
    "Kostenki14_published.DG",
    "GoyetQ116-1_published_all",
    "Vestonice16",
    "MA1_published.SG",
    "AfontovaGora3",
    "ElMiron",
    "Villabruna",
    "Iran_GanjDareh_N",
    "Russia_Ust_Ishim.DG",
    "Papuan.DG",
    "Han.DG",
    "Onge.DG",
    "Ami.DG",
    "Mixe.DG",
)

# AADR v66.p1 relabelled the whole compendium: the ".DG" suffixes are gone,
# site names were folded into period labels (the Swat Valley series is now
# "Pakistan_IA" / "Pakistan_LBA" / "Pakistan_Historic*"), and outliers,
# relatives and duplicates are marked with hyphen suffixes ("-o", "-Dup",
# "-QCremove", "-oRelative"). The labels below are the v66.p1 equivalents,
# read from the release's .ind files on 2026-10-31. The older labels above are
# kept so earlier .p1 releases still resolve.
BASE_RIGHT_V66: tuple[str, ...] = (
    "Mbuti",
    "Russia_UstIshim_IUP",
    "Russia_Kostenki_UP",
    "Russia_Malta_UP",
    "Russia_AfontovaGora_UP",
    "Belgium_UP",
    "Czechia_Gravettian",
    "Spain_Magdalenian",
    "Luxembourg_Loschbour_Mesolithic",
    "Iran_GanjDareh_N",
    "Papuan",
    "Han",
    "Ami",
    "Mixe",
)

BASE_RIGHT = BASE_RIGHT + BASE_RIGHT_V66

# --------------------------------------------------------------------------
# ancient sources and context
# --------------------------------------------------------------------------

ANCIENT_SOUTH_ASIA: tuple[str, ...] = (
    # Indus Valley periphery: outlier individuals at Shahr-i-Sokhta (Iran) and
    # Gonur (Turkmenistan) plus the Rakhigarhi individual, which together form
    # the "Indus Periphery Cline" of Narasimhan et al. 2019.
    "Iran_ShahrISokhta_BA2",
    "Iran_ShahrISokhta_BA1",
    "Iran_ShahrISokhta_BA_o*",
    "Turkmenistan_Gonur_BA_o*",
    "Turkmenistan_Gonur1_BA*",
    "India_Rakhigarhi_H*",
    "Pakistan_SaiduSharif_H_contact*",
    "Pakistan_SaiduSharif_IA*",
    # Swat Valley protohistoric transect: the densest ancient South Asian
    # sample series, spanning the Steppe-admixture horizon.
    "Pakistan_SwatValleyProtohistoric*",
    "Pakistan_Swat*",
    "Pakistan_Udegram*",
    "Pakistan_Butkara*",
    "Pakistan_Aligrama*",
    "Pakistan_Barikot*",
    "Pakistan_Katelai*",
    "Pakistan_Loebanr*",
    "Pakistan_Gogdara*",
    # Roopkund: historical-period lake burials; the Roopkund_A group is South
    # Asian, Roopkund_B eastern Mediterranean, Roopkund_C East Asian.
    "India_Roopkund_A",
    "India_Roopkund_B",
    "India_Roopkund_C",
    # v66.p1 labels.
    "Iran_ShahriSokhta_BA1-1",
    "Iran_ShahriSokhta_BA2-2",
    "Iran_ShahriSokhta_BA3-3",
    "India_Harappan",
    "Pakistan_LBA",
    "Pakistan_IA",
    "Pakistan_ProtohistoricGraves",
    "Pakistan_EarlyHistoric_H",
    "Pakistan_Historic*",
    "India_Roopkund-A",
    "India_Roopkund-B",
    "India_Roopkund-C",
)

ANCIENT_IRAN_ANATOLIA: tuple[str, ...] = (
    "Iran_GanjDareh_N",
    "Iran_HajjiFiruz_C*",
    "Iran_TepeHissar_C*",
    "Iran_SehGabi_C*",
    "Iran_Wezmeh_N*",
    "Iran_Belt_Cave_M*",
    "Iran_HotuIIIb_M*",
    "Anatolia_N",
    "Turkey_N",
    "Turkey_Boncuklu_N*",
    "Turkey_Barcin_N*",
    "Levant_PPNB*",
    "Israel_PPNB",
    "Jordan_PPNB",
    "Natufian*",
    "Israel_Natufian*",
    # v66.p1 labels.
    "Iran_HajjiFiruz_N",
    "Iran_WezmehCave_N",
    "Iran_BeltCave_Mesolithic",
    "Iran_HotuCave_Mesolithic_HotuIIIb",
    "Iran_TepeAbdulHosein_N",
    "Turkey_PPN",
    "Turkey_Epipaleolithic",
    "Turkey_Catalhoyuk_EN",
)

ANCIENT_STEPPE_SIBERIA: tuple[str, ...] = (
    # Steppe MLBA is the proximate Steppe source in South Asian models.
    "Russia_Sintashta_MLBA*",
    "Kazakhstan_Sintashta_MLBA*",
    "Russia_Srubnaya*",
    "Russia_Andronovo*",
    "Kazakhstan_Andronovo*",
    "Russia_Krasnoyarsk_MLBA*",
    "Russia_Potapovka*",
    "Russia_Poltavka*",
    "Russia_Petrovka*",
    "Kazakhstan_Petrovka*",
    "Russia_Afanasievo*",
    "Russia_Yamnaya_Samara",
    "Russia_Yamnaya*",
    "Kazakhstan_Kumsay_EBA*",
    # Hunter-gatherer baselines: West/East Siberian and Eastern/Western
    # European HG, which anchor the deep structure the models sit inside.
    "Russia_Tyumen_HG",
    "Russia_Sosnoviy_HG",
    "Russia_Baikal_EN*",
    "Russia_Shamanka_EN*",
    "Russia_DevilsCave_N*",
    "Russia_Karelia_HG*",
    "Russia_Samara_HG*",
    "WHG",
    "EHG",
    "WSHG",
    "ESHG",
    # v66.p1 labels.
    "Russia_Chelyabinsk_MLBA_Sintashta",
    "Russia_MLBA_Sintashta",
    "Russia_Samara_LBA_Srubnaya",
    "Russia_Samara_MBA_Poltavka",
    "Russia_Samara_MBA_Potapovka",
    "Russia_Chelyabinsk_Petrovka",
    "Russia_KrasnoyarskKrai_MLBA",
    "Russia_KrasnoyarskKrai_MLBA_Andronovo",
    "Russia_Samara_EBA_Yamnaya",
    "Russia_Kalmykia_EBA_Yamnaya",
    "Kazakhstan_KumsayKyrykOba_EBA_Yamnaya",
    "Russia_Altai_Afanasievo",
    "Russia_Karelia_Mesolithic",
    "Russia_Karelia_Mesolithic_HG",
    "Russia_Tyumen_EN_Mesolithic",
    "Russia_Tyumen_N_HG",
    "Russia_Irkutsk_N_Pribaikal",
    "Serbia_IronGates_Mesolithic",
)

ANCIENT_CENTRAL_ASIA: tuple[str, ...] = (
    "Turkmenistan_Geoksyur_EN*",
    "Turkmenistan_Namazga*",
    "Uzbekistan_Bustan_BA*",
    "Uzbekistan_Sappali_Tepe_BA*",
    "Uzbekistan_Dzharkutan*",
    "Tajikistan_Ksirov_H*",
    "Tajikistan_Sarazm_EN*",
    "Kazakhstan_Botai*",
    "Kyrgyzstan_*_MLBA*",
    # v66.p1 labels (the Gonur / Sappali Tepe / Dzharkutan series is now
    # carried by period labels).
    "Turkmenistan_Eneolithic",
    "Turkmenistan_C",
    "Turkmenistan_BA",
    "Turkmenistan_BA1-1",
    "Turkmenistan_BA2-2",
    "Turkmenistan_BA3-3",
    "Uzbekistan_BA",
    "Uzbekistan_BA1-1",
    "Uzbekistan_BA2-2",
    "Uzbekistan_BA3-3",
    "Tajikistan_C",
    "Tajikistan_BA",
    "Kyrgyzstan_MLBA_Andronovo",
    "Kyrgyzstan_EBA_MLBA_Andronovo",
)

# --------------------------------------------------------------------------
# modern groups
# --------------------------------------------------------------------------

# The "Indian cline": present-day South Asian groups ordered roughly by the
# ratio of Iranian-plateau-related to AASI-related ancestry. Present on the
# Human Origins array, so these drive the PCA space.
MODERN_SOUTH_ASIA: tuple[str, ...] = (
    "Brahui.DG",
    "Brahui",
    "Balochi.DG",
    "Balochi",
    "Makrani.DG",
    "Makrani",
    "Pathan.DG",
    "Pathan",
    "Kalash.DG",
    "Kalash",
    "Burusho.DG",
    "Burusho",
    "Sindhi.DG",
    "Sindhi",
    "Punjabi.DG",
    "Punjabi*",
    "GujaratiA",
    "GujaratiB",
    "GujaratiC",
    "GujaratiD",
    "Gujarati*",
    "Bengali*",
    "Vishwabrahmin",
    "Tiwari_Brahmin",
    "Brahmin*",
    "Kapu",
    "Kamsali",
    "Kashmiri_Pandit",
    "Velamas",
    "Yadava",
    "Lodi",
    "Chamar",
    "Dharkar",
    "Dusadh",
    "Kol",
    "Kurmi",
    "Mala",
    "Madiga",
    "Relli",
    "Hallaki",
    "Kurumba",
    "Irula",
    "Paniya",
    "Palliyar",
    "Ulladan",
    "Malayan",
    "Mahadeo_Koli",
    "Kunbi",
    "Bhil",
    "Gond",
    "Juang",
    "Ho",
    "Santhal",
    "Asur",
    "Birhor",
    "Munda*",
    "Khonda_Dora",
    "Nihali",
    "Onge.DG",
    "Onge",
    "Great_Andamanese*",
    "Jarawa*",
    "Sinhalese",
    "Tamil*",
    "Telugu*",
    "Kannada*",
    "Nepali*",
    "Tharu*",
    "Chamar*",
    # v66.p1 labels.
    "Sindhi_Pakistan",
    "Sindhi_1",
    "Sindhi_2",
    "Pakistani",
    "Relli_1",
    "Relli_2",
)

# Enough global context for a user's coordinates to be interpretable and for
# the PCA space not to collapse onto South Asian structure alone.
MODERN_GLOBAL: tuple[str, ...] = (
    "French.DG",
    "French",
    "Sardinian.DG",
    "Sardinian",
    "Basque",
    "Russian.DG",
    "Russian",
    "Lithuanian",
    "Finnish",
    "Greek",
    "Italian_North",
    "Tuscan",
    "Spanish",
    "English",
    "Scottish",
    "Norwegian",
    "Hungarian",
    "Ukrainian",
    "Estonian",
    "Chechen",
    "Georgian",
    "Armenian",
    "Turkish",
    "Iranian.DG",
    "Iranian",
    "Druze",
    "Lebanese",
    "Palestinian",
    "Jordanian",
    "Bedouin*",
    "Saudi",
    "Yemenite_Jew",
    "Egyptian",
    "Moroccan",
    "Mozabite",
    "Somali",
    "Dinka.DG",
    "Yoruba.DG",
    "Mbuti.DG",
    "Biaka.DG",
    "Ju_hoan_North.DG",
    "Han.DG",
    "Han",
    "Japanese",
    "Korean",
    "Dai.DG",
    "Ami.DG",
    "Atayal.DG",
    "Cambodian",
    "Thai",
    "Vietnamese",
    "Burmese",
    "Tibetan*",
    "Sherpa*",
    "Uygur",
    "Hazara",
    "Turkmen",
    "Uzbek",
    "Kazakh",
    "Kyrgyz",
    "Tajik*",
    "Mongola",
    "Daur",
    "Hezhen",
    "Oroqen",
    "Yakut.DG",
    "Even",
    "Itelmen",
    "Chukchi",
    "Eskimo*",
    "Papuan.DG",
    "Australian*",
    "Karitiana.DG",
    "Mixe.DG",
    "Mayan",
    "Piapoco",
    "Quechua",
    "Surui.DG",
    "Chimp.REF",
    "Gorilla.REF",
    "Altai_Neanderthal.DG",
    "Vindija.DG",
    "Denisova.DG",
    # v66.p1 labels.
    "Jew_Yemenite",
    "Dinka",
    "Yoruba",
    "Mbuti",
    "Biaka",
    "Ju_hoan_North",
    "Dai",
    "Ami",
    "Atayal",
    "Kinh_Vietnamese",
    "Uyghur",
    "Kyrgyz_Kyrgyzstan",
    "Yakut",
    "Papuan",
    "Karitiana",
    "Mixe",
    "Surui",
    "Chimp",
    "Gorilla",
    "Altai_Neanderthal",
    "VindijaCave_Neanderthal",
    "Russia_Denisova",
)


# --------------------------------------------------------------------------
# relabelling: telling a rename apart from a real gap
# --------------------------------------------------------------------------

# Suffixes AADR used to mark the sequencing source of a present-day sample and
# dropped in v66.p1 ("Mbuti.DG" -> "Mbuti"). A miss on a suffixed label is a
# rename, not a gap, when the bare label resolved.
ALIAS_SUFFIXES: tuple[str, ...] = (".DG", ".SG", ".REF", "_published", "_published_all")

# Labels v66.p1 replaced outright, mapped to the labels that carry the same
# individuals in the new scheme. Read off the v66.p1 `.ind` files on
# 2026-10-31. This map exists only to classify a miss: resolution itself still
# works off the panel labels, so an older `.p1` release keeps resolving. A
# label absent from this map and absent from the release is a real gap.
RELABELLED: dict[str, tuple[str, ...]] = {
    # Swat Valley transect: per-site labels folded into period labels.
    "Pakistan_SwatValleyProtohistoric*": ("Pakistan_IA", "Pakistan_LBA", "Pakistan_Historic*"),
    "Pakistan_Swat*": ("Pakistan_IA", "Pakistan_LBA", "Pakistan_Historic*"),
    "Pakistan_Aligrama*": ("Pakistan_IA", "Pakistan_Historic*"),
    "Pakistan_Barikot*": ("Pakistan_IA", "Pakistan_Historic*"),
    "Pakistan_Butkara*": ("Pakistan_IA", "Pakistan_Historic*"),
    "Pakistan_Gogdara*": ("Pakistan_IA", "Pakistan_LBA"),
    "Pakistan_Katelai*": ("Pakistan_IA", "Pakistan_LBA"),
    "Pakistan_Loebanr*": ("Pakistan_IA", "Pakistan_LBA"),
    "Pakistan_Udegram*": ("Pakistan_IA", "Pakistan_Historic*"),
    "Pakistan_SaiduSharif_IA*": ("Pakistan_IA", "Pakistan_EarlyHistoric_H"),
    "Pakistan_SaiduSharif_H_contact*": ("Pakistan_Historic*", "Pakistan_EarlyHistoric_H"),
    # Indus periphery.
    "Iran_ShahrISokhta_BA1": ("Iran_ShahriSokhta_BA1-1",),
    "Iran_ShahrISokhta_BA2": ("Iran_ShahriSokhta_BA2-2",),
    "Iran_ShahrISokhta_BA_o*": ("Iran_ShahriSokhta_BA3-3",),
    "India_Rakhigarhi_H*": ("India_Harappan",),
    "India_Roopkund_A": ("India_Roopkund-A",),
    "India_Roopkund_B": ("India_Roopkund-B",),
    "India_Roopkund_C": ("India_Roopkund-C",),
    # Central Asia: site labels folded into country + period.
    "Turkmenistan_Gonur1_BA*": ("Turkmenistan_BA*",),
    "Turkmenistan_Gonur_BA_o*": ("Turkmenistan_BA*",),
    "Turkmenistan_Namazga*": ("Turkmenistan_C", "Turkmenistan_Eneolithic"),
    "Turkmenistan_Geoksyur_EN*": ("Turkmenistan_Eneolithic", "Turkmenistan_C"),
    "Uzbekistan_Bustan_BA*": ("Uzbekistan_BA*",),
    "Uzbekistan_Dzharkutan*": ("Uzbekistan_BA*",),
    "Uzbekistan_Sappali_Tepe_BA*": ("Uzbekistan_BA*",),
    "Tajikistan_Sarazm_EN*": ("Tajikistan_C",),
    "Tajikistan_Ksirov_H*": ("Tajikistan_Khatlon_KushanPeriod",),
    # Steppe and Siberia.
    "Russia_Sintashta_MLBA*": ("Russia_MLBA_Sintashta", "Russia_Chelyabinsk_MLBA_Sintashta"),
    "Kazakhstan_Sintashta_MLBA*": ("Kazakhstan_Andronovo",),
    "Russia_Petrovka*": ("Russia_Chelyabinsk_Petrovka",),
    "Kazakhstan_Petrovka*": ("Russia_Chelyabinsk_Petrovka", "Kazakhstan_Andronovo"),
    "Kazakhstan_Kumsay_EBA*": ("Kazakhstan_KumsayKyrykOba_EBA_Yamnaya",),
    "Russia_Poltavka*": ("Russia_Samara_MBA_Poltavka",),
    "Russia_Potapovka*": ("Russia_Samara_MBA_Potapovka",),
    "Russia_Srubnaya*": ("Russia_Samara_LBA_Srubnaya",),
    "Russia_Yamnaya*": ("Russia_Samara_EBA_Yamnaya", "Russia_Kalmykia_EBA_Yamnaya"),
    "Russia_Yamnaya_Samara": ("Russia_Samara_EBA_Yamnaya",),
    "Russia_Krasnoyarsk_MLBA*": ("Russia_KrasnoyarskKrai_MLBA*",),
    "Kyrgyzstan_*_MLBA*": ("Kyrgyzstan_MLBA_Andronovo", "Kyrgyzstan_EBA_MLBA_Andronovo"),
    "Russia_Karelia_HG*": ("Russia_Karelia_Mesolithic*",),
    "EHG": ("Russia_Karelia_Mesolithic_HG",),
    "WHG": ("Luxembourg_Loschbour_Mesolithic", "Serbia_IronGates_Mesolithic"),
    "WSHG": ("Russia_Tyumen_N_HG", "Russia_Tyumen_EN_Mesolithic"),
    "ESHG": ("Russia_Irkutsk_N_Pribaikal",),
    "Russia_Tyumen_HG": ("Russia_Tyumen_N_HG",),
    "Russia_Sosnoviy_HG": ("Russia_Tyumen_N_HG",),
    "Russia_Baikal_EN*": ("Russia_Irkutsk_N_Pribaikal",),
    "Russia_Shamanka_EN*": ("Russia_Irkutsk_N_Pribaikal",),
    "Russia_DevilsCave_N*": ("Russia_Irkutsk_N_Pribaikal",),
    # Upper Palaeolithic / Mesolithic right-set members.
    "Ust_Ishim_published.DG": ("Russia_UstIshim_IUP",),
    "Russia_Ust_Ishim.DG": ("Russia_UstIshim_IUP",),
    "Kostenki14_published.DG": ("Russia_Kostenki_UP",),
    "MA1_published.SG": ("Russia_Malta_UP", "Russia_AfontovaGora_UP"),
    "AfontovaGora3": ("Russia_AfontovaGora_UP",),
    "GoyetQ116-1_published_all": ("Belgium_UP",),
    "Vestonice16": ("Czechia_Gravettian",),
    "ElMiron": ("Spain_Magdalenian",),
    "Villabruna": ("Luxembourg_Loschbour_Mesolithic", "Serbia_IronGates_Mesolithic"),
    "Vindija.DG": ("VindijaCave_Neanderthal",),
    "Denisova.DG": ("Russia_Denisova",),
    # West Asia.
    "Anatolia_N": ("Turkey_N", "Turkey_Catalhoyuk_EN"),
    "Turkey_Barcin_N*": ("Turkey_N", "Turkey_Catalhoyuk_EN"),
    "Turkey_Boncuklu_N*": ("Turkey_PPN", "Turkey_N"),
    "Natufian*": ("Israel_Natufian",),
    "Israel_PPNB": ("Jordan_PPNB",),
    "Levant_PPNB*": ("Jordan_PPNB",),
    "Iran_Belt_Cave_M*": ("Iran_BeltCave_Mesolithic",),
    "Iran_HotuIIIb_M*": ("Iran_HotuCave_Mesolithic_HotuIIIb",),
    "Iran_HajjiFiruz_C*": ("Iran_HajjiFiruz_N",),
    "Iran_Wezmeh_N*": ("Iran_WezmehCave_N",),
    # Present-day groups renamed rather than dropped.
    "Kyrgyz": ("Kyrgyz_Kyrgyzstan",),
    "Uygur": ("Uyghur",),
    "Vietnamese": ("Kinh_Vietnamese",),
    "Yemenite_Jew": ("Jew_Yemenite",),
    "Relli": ("Relli_1", "Relli_2"),
    "Sindhi": ("Sindhi_1", "Sindhi_2", "Sindhi_Pakistan"),
    "Sindhi.DG": ("Sindhi_1", "Sindhi_2", "Sindhi_Pakistan"),
}


@dataclass(frozen=True)
class PanelGroup:
    """A named block of the reference panel."""

    name: str
    region: str
    labels: tuple[str, ...]
    role: str  # "target_cline" | "source" | "right" | "context"
    period: str  # "Modern" | "Ancient" | "Mixed"


PANEL: tuple[PanelGroup, ...] = (
    PanelGroup("ancient_south_asia", "South Asia", ANCIENT_SOUTH_ASIA, "target_cline", "Ancient"),
    PanelGroup(
        "ancient_iran_anatolia", "West Asia", ANCIENT_IRAN_ANATOLIA, "source", "Ancient"
    ),
    PanelGroup(
        "ancient_steppe_siberia", "Steppe/Siberia", ANCIENT_STEPPE_SIBERIA, "source", "Ancient"
    ),
    PanelGroup("ancient_central_asia", "Central Asia", ANCIENT_CENTRAL_ASIA, "source", "Ancient"),
    PanelGroup("modern_south_asia", "South Asia", MODERN_SOUTH_ASIA, "target_cline", "Modern"),
    PanelGroup("modern_global", "Global", MODERN_GLOBAL, "context", "Modern"),
)

# Regions whose present-day individuals define the PCA space.
PCA_FIT_LABELS: tuple[str, ...] = MODERN_SOUTH_ASIA + MODERN_GLOBAL


@dataclass
class Resolution:
    """Which requested labels were found in a release, and which were not."""

    matched: dict[str, str] = field(default_factory=dict)  # group_id -> panel block
    unmatched: list[str] = field(default_factory=list)  # requested labels with no match
    # Right-set labels with no match, kept apart from `unmatched` because the
    # right set is applied to every panel, so mixing the two would make a
    # caller's own panel look as if it had asked for the outgroups too.
    unmatched_right: list[str] = field(default_factory=list)
    roles: dict[str, str] = field(default_factory=dict)  # group_id -> role
    # Every group a BASE_RIGHT label resolved to, whatever role it ended up
    # with. `roles` cannot carry this: a conventional outgroup is usually also
    # a panel member (Mbuti and Papuan are in `modern_global`), and the panel
    # block's role wins there, so the right set would otherwise be invisible
    # to anything reading `roles` — including a caller assembling a right set.
    right_set: list[str] = field(default_factory=list)

    @property
    def group_ids(self) -> list[str]:
        return sorted(self.matched)

    def classify_unmatched(self) -> UnmatchedReport:
        """Split the misses into renames and real gaps.

        See :class:`UnmatchedReport` for why the distinction matters.
        """
        return classify_unmatched(
            self.unmatched + self.unmatched_right, sorted(self.matched)
        )


@dataclass
class UnmatchedReport:
    """Which panel labels missed, and whether the miss matters.

    The panel deliberately carries labels from several AADR releases, so most
    misses on any one release are a label the release renamed and nothing is
    lost. Reporting the two together overstates the gap: on v66.p1 the raw
    count is 137 labels, of which only a minority are groups the release does
    not contain at all. ``missing`` is the number a reviewer should act on.
    """

    superseded: list[str] = field(default_factory=list)  # renamed; replacement resolved
    missing: list[str] = field(default_factory=list)  # absent from the release

    def as_dict(self) -> dict[str, Any]:
        return {
            "superseded_labels": sorted(self.superseded),
            "missing_labels": sorted(self.missing),
            "n_superseded": len(self.superseded),
            "n_missing": len(self.missing),
        }


def _strip_alias_suffix(label: str) -> str | None:
    """``"Mbuti.DG"`` -> ``"Mbuti"``; ``None`` when the label carries no suffix."""
    bare = label.removesuffix("*")
    for suffix in ALIAS_SUFFIXES:
        if bare.endswith(suffix) and len(bare) > len(suffix):
            return bare[: -len(suffix)]
    return None


def classify_unmatched(unmatched: list[str], available: list[str]) -> UnmatchedReport:
    """Decide, for each miss, whether another label already covers those samples.

    A miss is *superseded* when the release carries the same individuals under
    a different label: either the label is a sequencing-source alias whose bare
    form resolved (``Mbuti.DG`` where ``Mbuti`` exists), or :data:`RELABELLED`
    names a replacement that resolved. Everything else is *missing*.

    Args:
        unmatched: Panel labels that matched nothing.
        available: The group IDs the release does contain.

    Returns:
        An :class:`UnmatchedReport`.
    """
    pool = sorted(set(available))
    report = UnmatchedReport()
    for label in sorted(set(unmatched)):
        bare = _strip_alias_suffix(label)
        if bare is not None and any(_matches(bare, g) for g in pool):
            report.superseded.append(label)
            continue
        replacements = RELABELLED.get(label, ())
        if any(_matches(r, g) for r in replacements for g in pool):
            report.superseded.append(label)
            continue
        report.missing.append(label)
    return report


def _matches(label: str, group_id: str) -> bool:
    """Exact match, or prefix match when the label ends in ``*``."""
    if label.endswith("*"):
        prefix = label[:-1]
        return group_id.startswith(prefix)
    return group_id == label


def resolve(available: list[str], panel: tuple[PanelGroup, ...] = PANEL) -> Resolution:
    """Match panel labels against the group IDs present in a release.

    Args:
        available: Every ``Group ID`` seen in the ``.anno`` file.
        panel: The panel blocks to resolve.

    Returns:
        A :class:`Resolution`. A requested label that matches nothing lands in
        ``unmatched`` so the build can report it without failing.
    """
    res = Resolution()
    pool = sorted(set(available))
    for block in panel:
        for label in block.labels:
            hits = [g for g in pool if _matches(label, g)]
            if not hits:
                res.unmatched.append(label)
                continue
            for g in hits:
                # First block to claim a group wins, so ancient blocks (listed
                # first) are not overwritten by a modern prefix pattern.
                res.matched.setdefault(g, block.name)
                res.roles.setdefault(g, block.role)
    # The right set is a role, not a block, and it is always applied: a
    # population may be both a panel member and a standing outgroup (Onge.DG
    # is the AASI proxy *and* a conventional right population). setdefault, not
    # assignment: an explicit panel block's role wins, because that is the role
    # the panel was designed around.
    #
    # A right label that matches nothing is reported like any other miss. It
    # used to be dropped silently, which hid the one miss that matters most:
    # the right set is where a missing outgroup (Onge, the usual AASI proxy)
    # changes what qpAdm can resolve, not just which populations are listed.
    for label in BASE_RIGHT:
        hits = [g for g in pool if _matches(label, g)]
        if not hits:
            res.unmatched_right.append(label)
            continue
        for g in hits:
            res.matched.setdefault(g, "right")
            res.roles.setdefault(g, "right")
            if g not in res.right_set:
                res.right_set.append(g)
    res.right_set.sort()
    return res
