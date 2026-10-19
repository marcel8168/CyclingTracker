"""Build hooks for Android manifest attributes unsupported by Buildozer."""

from pathlib import Path
from xml.etree import ElementTree

ANDROID_NAMESPACE = 'http://schemas.android.com/apk/res/android'
SERVICE_NAME = 'org.cyclingtracker.cyclingtracker.ServiceRide'


def patch_service_foreground_type(manifest_path):
    """Declare the location type on Buildozer's generated ride service."""
    ElementTree.register_namespace('android', ANDROID_NAMESPACE)
    parser = ElementTree.XMLParser(
        target=ElementTree.TreeBuilder(insert_comments=True)
    )
    tree = ElementTree.parse(manifest_path, parser=parser)
    name_attribute = f'{{{ANDROID_NAMESPACE}}}name'
    service_elements = [
        element
        for element in tree.getroot().iter()
        if element.tag == 'service'
        and element.get(name_attribute) == SERVICE_NAME
    ]
    if len(service_elements) != 1:
        raise RuntimeError(
            f'Expected one {SERVICE_NAME} declaration in {manifest_path}, '
            f'found {len(service_elements)}'
        )

    service = service_elements[0]
    service.set(f'{{{ANDROID_NAMESPACE}}}foregroundServiceType', 'location')
    service.set(f'{{{ANDROID_NAMESPACE}}}exported', 'false')
    tree.write(manifest_path, encoding='utf-8', xml_declaration=True)


def after_apk_build(_context):
    """Patch generated manifests after python-for-android renders them."""
    for manifest_path in (
        Path('src/main/AndroidManifest.xml'),
        Path('AndroidManifest.xml'),
    ):
        if not manifest_path.is_file():
            raise FileNotFoundError(
                f'python-for-android did not generate {manifest_path}'
            )
        patch_service_foreground_type(manifest_path)
