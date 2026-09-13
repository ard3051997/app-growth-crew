"""AdMob App mappings between app ID and package names."""

from __future__ import annotations

# AdMob app ID to package name mapping for the main admob account
ADMOB_ADMOB_APP_MAPPING = {
    "ca-app-pub-9800009975517669~1056844453": "com.finance.loan.emicalculator",
    "ca-app-pub-9800009975517669~1066072683": "ryn-vpn-fast-proxy-unblocker/id1493328027",  # ryn ios
    "ca-app-pub-9800009975517669~1367422609": "com.code1.agecalculator",
    "ca-app-pub-9800009975517669~3399238313": "com.secure.cryptovpn",
    "ca-app-pub-9800009975517669~4142734188": "com.code1.agecalculator",
    "ca-app-pub-9800009975517669~5688678700": "com.ponicamedia.voicechanger",
    "ca-app-pub-9800009975517669~5716392117": "com.cama.app.huge80sclock",
    "ca-app-pub-9800009975517669~6098660092": "com.secure.cryptovpn",  # ryn android
    "ca-app-pub-9800009975517669~6461015261": "oh.mypackage.hasnoname",
    "ca-app-pub-9800009975517669~9888025977": "com.hammersecurity",
    "ca-app-pub-9800009975517669~1558541367": "com.hindi.english.translate.language.word.dictionary",
    "ca-app-pub-9800009975517669~6718885547": "net.smartlogic.indiagst",
    "ca-app-pub-9800009975517669~3297390522": "com.bankapp.hi.banklist",
    "ca-app-pub-9800009975517669~5898954043": "huge-digital-clock/id1515003825",
    "ca-app-pub-9800009975517669~2942184104": "emi-calculator-loan-planner/id914793563",
    "ca-app-pub-9800009975517669~8482356174": "voice.changer.auto.tune.editor.recorder",
}


def get_app_id_for_package(package_name: str, publisher_id: str | None = None) -> str | None:
    """Find the AdMob app ID for a given package name.

    Args:
        package_name: Target package name (e.g. com.finance.loan.emicalculator)
        publisher_id: Optional publisher ID (e.g. pub-9800009975517669) to filter the search

    Returns:
        The matched AdMob app ID or None.
    """

    def normalize(p: str) -> str:
        return p.replace("/", "-")

    target = normalize(package_name)
    for app_id, pkg in ADMOB_ADMOB_APP_MAPPING.items():
        if normalize(pkg) == target:
            if publisher_id and publisher_id not in app_id:
                continue
            return app_id
    return None


def get_package_for_app_id(app_id: str) -> str | None:
    """Find the package name for a given AdMob app ID."""
    pkg = ADMOB_ADMOB_APP_MAPPING.get(app_id)
    if pkg and "/id" in pkg:
        return pkg.replace("/id", "-id")
    return pkg
