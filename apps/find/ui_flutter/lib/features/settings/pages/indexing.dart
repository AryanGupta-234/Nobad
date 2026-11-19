/// Indexing: what to search.
library;

import 'package:flutter/widgets.dart';

import '../settings_parts.dart';

class IndexingPage extends StatelessWidget {
  const IndexingPage({super.key});

  @override
  Widget build(BuildContext context) => const Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        SettingsGroup('What to search', rows: [
          FoldersSetting('roots', 'Folders to search',
              "Empty: your profile folder and every fixed drive (never other people's profiles or Windows itself)."),
          FoldersSetting('exclude', 'Never search', 'These folders and files are skipped and removed from the index.'),
          SwitchSetting('content', 'Read the text inside files',
              'Documents, PDFs, code, notes and e-mail files. Off: names only.'),
          TextSetting('content_max_mb', 'Largest file to read (MB)', 'Bigger files are still found by name.',
              number: true),
          SwitchSetting('ocr', 'Words in photos and scans',
              'Screenshots, photos of documents and scanned PDFs, read with the OCR built into Windows (offline). '
                  'Slower, so it runs after everything else.'),
          SwitchSetting('src_mail', 'E-mail files', '.eml and .mbox files found on your drives.'),
          SwitchSetting('index_removable', 'USB and external drives',
              'Indexed while plugged in. Their files stay findable (marked “not connected”) when you unplug them. '
                  'Turning this off removes their files from the index.'),
          SwitchSetting('index_network', 'Network drives',
              'Mapped network drives (Z: and so on). Big shares take a while and use your home or office network.'),
        ]),
      ]);
}
