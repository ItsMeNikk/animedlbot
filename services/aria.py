from __future__ import annotations
import aria2p
from typing import List, Optional

# Setup the connection to the aria2c RPC server
# This assumes the bot and aria2c are running on the same machine.
# If they are on different machines, change 'host' and 'port' accordingly.
api = aria2p.API(
    aria2p.Client(
        host="http://127.0.0.1",
        port=6800,
        secret=""
    )
)

class AriaDownload:
    """A class to represent and manage an aria2 download."""
    def __init__(self, download: aria2p.Download):
        self._download = download

    @property
    def gid(self) -> str:
        return self._download.gid

    @property
    def name(self) -> str:
        return self._download.name

    @property
    def is_complete(self) -> bool:
        self._download.update()
        return self._download.is_complete

    @property
    def progress(self) -> float:
        self._download.update()
        return self._download.progress

    @property
    def progress_string(self) -> str:
        self._download.update()
        return self._download.progress_string()

    @property
    def eta(self) -> str:
        """Human-readable ETA string for the download, or 'unknown' on failure."""
        self._download.update()
        try:
            return self._download.eta_string()
        except Exception:
            return "unknown"

    @property
    def files(self) -> List[aria2p.File]:
        self._download.update()
        return self._download.files

    def remove(self, clean: bool = True) -> bool:
        """Removes the download from aria2c.
        If clean is True, it also deletes the downloaded files.
        """
        return self._download.remove(files=clean)

def add_magnet(magnet_uri: str) -> Optional[AriaDownload]:
    """Adds a magnet link to aria2c for downloading."""
    try:
        download = api.add_magnet(magnet_uri)
        return AriaDownload(download)
    except Exception as e:
        print(f"Failed to add magnet link to aria2c: {e}")
        return None

def get_download(gid: str) -> Optional[AriaDownload]:
    """Gets a download by its GID (Group ID)."""
    try:
        download = api.get_download(gid)
        return AriaDownload(download)
    except Exception as e:
        print(f"Failed to get download {gid} from aria2c: {e}")
        return None