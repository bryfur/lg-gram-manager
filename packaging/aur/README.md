# AUR packaging

Files for the `lg-gram-manager` package on the Arch User Repository.

Release procedure:

1. Tag the release on GitHub (tags are bare versions, e.g. `1.1.0`) and push the tag.
2. Set `pkgver` (and reset `pkgrel=1`) in `PKGBUILD`.
3. In a copy of this directory: `updpkgsums && makepkg --printsrcinfo > .SRCINFO`
4. Test with `makepkg -si`.
5. Commit `PKGBUILD`, `.SRCINFO` and `lg-gram-manager.install` to the AUR git repo
   (`ssh://aur@aur.archlinux.org/lg-gram-manager.git`) and push.
