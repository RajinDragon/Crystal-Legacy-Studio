from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
import json
import struct

from PIL import Image
import lz4.block


@dataclass
class ExtractedTexture:
    name: str
    width: int
    height: int
    texture_format: int
    source_bundle: str
    source_node: str
    output_file: str
    path_id: int


@dataclass
class ExtractedSprite:
    name: str
    rect: tuple[float, float, float, float]
    source_bundle: str
    source_node: str
    path_id: int


def _cstring(data: bytes, offset: int) -> tuple[bytes, int]:
    end = data.index(b"\0", offset)
    return data[offset:end], end + 1


def _decompress(data: bytes, flags: int, expected_size: int) -> bytes:
    compression = flags & 0x3F
    if compression == 0:
        return data
    if compression in (2, 3):
        return lz4.block.decompress(data, uncompressed_size=expected_size)
    raise ValueError(f"Unsupported UnityFS compression type {compression}.")


def unpack_unityfs(bundle: Path) -> dict[str, bytes]:
    """Read a UnityFS file and return its internal named nodes.

    This is intentionally internal and dependency-light. It handles the UnityFS
    v7/LZ4 layout used by FF1 Pixel Remaster character Addressables bundles.
    """
    raw = Path(bundle).read_bytes()
    offset = 0
    signature, offset = _cstring(raw, offset)
    if signature != b"UnityFS":
        raise ValueError(f"{Path(bundle).name} is not a UnityFS bundle.")
    fmt = struct.unpack_from(">I", raw, offset)[0]
    offset += 4
    _unity_version, offset = _cstring(raw, offset)
    _revision, offset = _cstring(raw, offset)
    _recorded_size, compressed_info_size, uncompressed_info_size, flags = struct.unpack_from(">QIII", raw, offset)
    offset += 20
    aligned = (offset + 15) & ~15 if fmt >= 7 else offset

    if flags & 0x80:
        compressed_info = raw[-compressed_info_size:]
        data_start = aligned
        data_end = len(raw) - compressed_info_size
    else:
        compressed_info = raw[aligned:aligned + compressed_info_size]
        data_start = aligned + compressed_info_size
        data_end = len(raw)

    info = _decompress(compressed_info, flags, uncompressed_info_size)
    cursor = 16
    block_count = struct.unpack_from(">I", info, cursor)[0]
    cursor += 4
    blocks = []
    for _ in range(block_count):
        uncompressed_size, compressed_size, block_flags = struct.unpack_from(">IIH", info, cursor)
        cursor += 10
        blocks.append((uncompressed_size, compressed_size, block_flags))
    node_count = struct.unpack_from(">I", info, cursor)[0]
    cursor += 4
    nodes = []
    for _ in range(node_count):
        node_offset, node_size, node_flags = struct.unpack_from(">QQI", info, cursor)
        cursor += 20
        node_name, cursor = _cstring(info, cursor)
        nodes.append((node_offset, node_size, node_flags, node_name.decode("utf-8", "replace")))

    compressed_data = raw[data_start:data_end]
    data_cursor = 0
    uncompressed = bytearray()
    for expected_size, compressed_size, block_flags in blocks:
        chunk = compressed_data[data_cursor:data_cursor + compressed_size]
        data_cursor += compressed_size
        uncompressed.extend(_decompress(chunk, block_flags, expected_size))

    return {name: bytes(uncompressed[start:start + size]) for start, size, _flags, name in nodes}


def _aligned_string(data: bytes, offset: int) -> tuple[str, int]:
    length = struct.unpack_from("<i", data, offset)[0]
    offset += 4
    if length < 0 or offset + length > len(data):
        raise ValueError("Invalid Unity serialized string.")
    text = data[offset:offset + length].decode("utf-8", "replace")
    offset += length
    return text, (offset + 3) & ~3


def _serialized_objects(data: bytes) -> tuple[int, list[int], list[tuple[int, int, int, int]]]:
    if len(data) < 24:
        raise ValueError("Serialized node is too small.")
    metadata_size, _file_size, version, data_offset = struct.unpack_from(">4I", data, 0)
    if version < 14 or version > 22:
        raise ValueError(f"Unsupported Unity serialized-file version {version}.")
    offset = 20
    _unity_version, offset = _cstring(data, offset)
    offset += 4  # target platform
    enable_type_tree = data[offset]
    offset += 1
    type_count = struct.unpack_from("<i", data, offset)[0]
    offset += 4
    class_ids: list[int] = []
    for _ in range(type_count):
        class_id = struct.unpack_from("<i", data, offset)[0]
        offset += 4
        offset += 1 + 2  # stripped + script type index
        if class_id == 114:
            offset += 16
        offset += 16  # old type hash
        if enable_type_tree:
            node_count, string_size = struct.unpack_from("<ii", data, offset)
            offset += 8 + node_count * 32 + string_size
        if version >= 21:
            dependency_count = struct.unpack_from("<i", data, offset)[0]
            offset += 4 + dependency_count * 4
        class_ids.append(class_id)

    object_count = struct.unpack_from("<i", data, offset)[0]
    offset += 4
    objects = []
    for _ in range(object_count):
        offset = (offset + 3) & ~3
        path_id = struct.unpack_from("<q", data, offset)[0]
        offset += 8
        byte_start = struct.unpack_from("<Q" if version >= 22 else "<I", data, offset)[0]
        offset += 8 if version >= 22 else 4
        byte_size = struct.unpack_from("<I", data, offset)[0]
        offset += 4
        type_index = struct.unpack_from("<i", data, offset)[0]
        offset += 4
        objects.append((path_id, byte_start, byte_size, type_index))
    if 20 + metadata_size > len(data) or data_offset > len(data):
        raise ValueError("Invalid serialized-file bounds.")
    return data_offset, class_ids, objects


def _texture_from_object(obj: bytes, stream_nodes: dict[str, bytes]) -> tuple[str, int, int, int, bytes]:
    offset = 0
    name, offset = _aligned_string(obj, offset)
    offset += 4  # forced fallback format
    offset += 1  # downscale fallback
    offset = (offset + 3) & ~3
    width, height, _complete_size, texture_format, _mip_count = struct.unpack_from("<5i", obj, offset)
    offset += 20
    offset += 4  # four booleans
    offset += 12  # streaming priority, image count, dimension
    offset += 24  # GLTextureSettings
    offset += 8  # lightmap format, color space
    image_size = struct.unpack_from("<i", obj, offset)[0]
    offset += 4
    if image_size < 0 or offset + image_size > len(obj):
        raise ValueError(f"Invalid texture payload for {name}.")
    pixels = obj[offset:offset + image_size]
    offset = (offset + image_size + 3) & ~3

    if not pixels and offset + 16 <= len(obj):
        stream_offset = struct.unpack_from("<Q", obj, offset)[0]
        stream_size = struct.unpack_from("<I", obj, offset + 8)[0]
        path_len = struct.unpack_from("<i", obj, offset + 12)[0]
        path_start = offset + 16
        stream_path = obj[path_start:path_start + path_len].decode("utf-8", "replace")
        node = stream_nodes.get(stream_path) or stream_nodes.get(Path(stream_path).name)
        if node is None:
            for node_name, node_data in stream_nodes.items():
                if node_name.endswith(Path(stream_path).name):
                    node = node_data
                    break
        if node is not None:
            pixels = node[stream_offset:stream_offset + stream_size]

    if not pixels:
        raise ValueError(f"Texture {name} contains no readable pixel payload.")
    return name, width, height, texture_format, pixels


def _decode_texture(width: int, height: int, texture_format: int, pixels: bytes) -> Image.Image:
    expected = width * height
    if texture_format == 4:  # RGBA32
        image = Image.frombytes("RGBA", (width, height), pixels[:expected * 4])
    elif texture_format == 3:  # RGB24
        image = Image.frombytes("RGB", (width, height), pixels[:expected * 3]).convert("RGBA")
    elif texture_format == 5:  # ARGB32
        image = Image.frombytes("RGBA", (width, height), pixels[:expected * 4], "raw", "ARGB")
    elif texture_format == 14:  # BGRA32
        image = Image.frombytes("RGBA", (width, height), pixels[:expected * 4], "raw", "BGRA")
    else:
        raise ValueError(f"Unsupported Texture2D format {texture_format}.")
    return image.transpose(Image.Transpose.FLIP_TOP_BOTTOM)



def _sprite_from_object(obj: bytes) -> tuple[str, tuple[float, float, float, float]]:
    """Read the stable leading fields of a Unity 2019.4 Sprite object.

    FF1PR Sprite objects begin with m_Name followed by m_Rect (x, y, width,
    height). The rectangle uses Unity's bottom-left texture coordinates.
    Reading this small stable prefix is sufficient to preserve animation-frame
    identity without depending on a complete Unity type-tree implementation.
    """
    name, offset = _aligned_string(obj, 0)
    if offset + 16 > len(obj):
        raise ValueError(f"Sprite {name} does not contain a readable rectangle.")
    rect = struct.unpack_from("<4f", obj, offset)
    x, y, width, height = rect
    if width <= 0 or height <= 0 or width > 4096 or height > 4096:
        raise ValueError(f"Sprite {name} has an invalid rectangle {rect}.")
    return name, (x, y, width, height)


def extract_bundle_textures(bundle: Path, output_dir: Path) -> list[ExtractedTexture]:
    """Extract readable Texture2D objects from one FF1PR character bundle.

    The original bundle is untouched. PNGs plus a JSON inventory are emitted so
    Studio can preview, rename, mix, and package battle/overworld artwork while
    still retaining the compiled source bundle for exact deployment.
    """
    bundle = Path(bundle)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    nodes = unpack_unityfs(bundle)
    results: list[ExtractedTexture] = []
    sprites: list[ExtractedSprite] = []
    used_names: dict[str, int] = {}

    for node_name, node_data in nodes.items():
        if node_name.lower().endswith(".ress"):
            continue
        try:
            data_offset, class_ids, objects = _serialized_objects(node_data)
        except Exception:
            continue
        for path_id, byte_start, byte_size, type_index in objects:
            if type_index < 0 or type_index >= len(class_ids):
                continue
            class_id = class_ids[type_index]
            obj = node_data[data_offset + byte_start:data_offset + byte_start + byte_size]
            if class_id == 213:  # Sprite
                try:
                    name, rect = _sprite_from_object(obj)
                    sprites.append(ExtractedSprite(name, rect, bundle.name, node_name, path_id))
                except Exception:
                    pass
                continue
            if class_id != 28:  # Texture2D
                continue
            try:
                name, width, height, texture_format, pixels = _texture_from_object(obj, nodes)
                image = _decode_texture(width, height, texture_format, pixels)
            except Exception:
                continue
            safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in name).strip("._") or f"Texture_{path_id}"
            count = used_names.get(safe.lower(), 0)
            used_names[safe.lower()] = count + 1
            filename = f"{safe}{'' if count == 0 else '_' + str(count + 1)}.png"
            target = output_dir / filename
            image.save(target)
            results.append(ExtractedTexture(name, width, height, texture_format, bundle.name, node_name, filename, path_id))

    inventory = {
        "format": "CrystalLegacyBundleExtraction",
        "version": 1,
        "sourceBundle": bundle.name,
        "textures": [asdict(item) for item in results],
        "sprites": [asdict(item) for item in sprites],
    }
    (output_dir / "bundle-extraction.json").write_text(json.dumps(inventory, indent=2), encoding="utf-8")
    return results
