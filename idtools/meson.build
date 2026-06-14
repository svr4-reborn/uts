project('idtools', 'c',
  version: '1.0',
  default_options: [
    'c_std=gnu89',
    'buildtype=release', # Matches the -O optimization flag
  ]
)

cc = meson.get_compiler('c')

# Feature defines mirroring the historical MORECPP set and K&R compat flags
# get_supported_arguments() safely applies the suppression flags if the compiler understands them
add_project_arguments(
  '-fcommon',
  '-DAT386',
  '-DWEITEK',
  '-DVPIX',
  '-DMERGE',
  cc.get_supported_arguments(
    '-Wno-implicit-int',
    '-Wno-implicit-function-declaration'
  ),
  language: 'c'
)

# Compiled C tools
executable('idconfig',
  'idconfig.c',
  install: true
)

executable('idmkunix',
  'idmkunix.c',
  install: true
)

executable('idval',
  'idval.c',
  install: true
)

# Shell driver scripts shipped as-is
install_data(
  'idbuild',
  'idtune',
  'idreboot',
  install_dir: get_option('bindir'),
  install_mode: 'rwxr-xr-x' # Ensures they are executable (chmod 755)
)
