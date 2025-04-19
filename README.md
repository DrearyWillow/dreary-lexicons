# dreary-lexicons
4fun. just playing around.


## dreary-tunes
youtube, soundcloud, bandcamp playlist links should work. attempts to not dedupe records.

### TODO
* imports are ugly, a lot of junk dependencies, including my own bsky_utils lol.
* i can probably import yt-dlp directly (and probably don't need it, but i'm lazy and there's edge cases)
* support reading from file, not just url (yt-dlp large playlists are a pain)
* cli for picking existing playlists
* adding individual tracks, not just mirroring playlists
* something a little more elegant than `config.json` for auth lol
* applyWrites (split_list)
* reconsider playlistitem index. atproto ordered lists kinda suck
* fix camelCase and snake_case lol
* yield, not return, existing records
* proper arguments
* delete all records helper function
* caching
* implement debug mode for print_json
* not gonna make an appview bro you can't make me

### Acknowledgements
* [bandcamp-dl](https://github.com/iheanyi/bandcamp-dl)
* [scdl](https://github.com/scdl-org/scdl)
* [yt-dlp](https://github.com/yt-dlp/yt-dlp)