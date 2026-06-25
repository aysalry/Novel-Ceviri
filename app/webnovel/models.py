from dataclasses import dataclass, field


@dataclass
class ChapterRef:
    title: str
    url: str
    locked: bool = False


@dataclass
class NovelInfo:
    title: str
    source_url: str
    author: str = ''
    cover_url: str | None = None
    chapters: list[ChapterRef] = field(default_factory=list)
    genres: list[str] = field(default_factory=list)


@dataclass
class ChapterContent:
    title: str
    paragraphs: list[str]


@dataclass
class SearchResult:
    title: str
    url: str
    source_name: str
    cover_url: str | None = None
