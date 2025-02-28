{pkgs}: {
  deps = [
    pkgs.libffi
    pkgs.rustc
    pkgs.pkg-config
    pkgs.libxcrypt
    pkgs.libiconv
    pkgs.cargo
    pkgs.cacert
    pkgs.libsodium
    pkgs.postgresql
    pkgs.openssl
  ];
}
