import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:supplyos_core/supplyos_core.dart';

import 'theme.dart';
import 'providers.dart';

class TaskPage extends StatelessWidget {
  const TaskPage({
    required this.eyebrow,
    required this.title,
    required this.children,
    this.actions = const [],
    super.key,
  });
  final String eyebrow;
  final String title;
  final List<Widget> children;
  final List<Widget> actions;
  @override
  Widget build(BuildContext context) => ListView(
    padding: const EdgeInsets.fromLTRB(20, 20, 20, 40),
    keyboardDismissBehavior: ScrollViewKeyboardDismissBehavior.onDrag,
    children: [
      Text(
        eyebrow.toUpperCase(),
        style: Theme.of(context).textTheme.labelSmall,
      ),
      const SizedBox(height: 8),
      Text(
        title.toUpperCase(),
        style: Theme.of(context).textTheme.headlineLarge,
      ),
      if (actions.isNotEmpty)
        Padding(
          padding: const EdgeInsets.only(top: 16),
          child: Wrap(spacing: 10, runSpacing: 10, children: actions),
        ),
      const SizedBox(height: 24),
      for (final child in children)
        Padding(padding: const EdgeInsets.only(bottom: 16), child: child),
    ],
  );
}

class QueryPanel<T, A> extends ConsumerWidget {
  const QueryPanel({
    required this.query,
    required this.argument,
    required this.builder,
    super.key,
  });
  final SessionQuery<T, A> query;
  final A argument;
  final Widget Function(T) builder;
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    ref.listen(adminIntentsProvider.select((registry) => registry.revision), (
      _,
      _,
    ) {
      ref.read(query.refreshProvider(argument))();
    });
    return ref
        .watch(query.provider(argument))
        .when(
          skipLoadingOnRefresh: false,
          skipLoadingOnReload: false,
          loading: () => const LoadingNotice(),
          error: (error, _) => ErrorNotice(
            error: error,
            onRetry: ref.read(query.refreshProvider(argument)),
          ),
          data: builder,
        );
  }
}

class LoadingNotice extends StatelessWidget {
  const LoadingNotice({super.key});
  @override
  Widget build(BuildContext context) => Semantics(
    liveRegion: true,
    child: Padding(
      padding: EdgeInsets.all(24),
      child: Row(
        children: [
          SizedBox(
            width: 22,
            height: 22,
            child: CircularProgressIndicator(strokeWidth: 2),
          ),
          SizedBox(width: 14),
          Expanded(child: Text('Loading current server data...')),
        ],
      ),
    ),
  );
}

class ErrorNotice extends StatelessWidget {
  const ErrorNotice({required this.error, required this.onRetry, super.key});
  final Object error;
  final VoidCallback onRetry;
  @override
  Widget build(BuildContext context) => Semantics(
    liveRegion: true,
    child: Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              AppFailure.safe(error).message,
              style: TextStyle(color: Theme.of(context).colorScheme.error),
            ),
            const SizedBox(height: 12),
            OutlinedButton.icon(
              onPressed: onRetry,
              icon: const Icon(Icons.refresh),
              label: const Text('Retry server read'),
            ),
          ],
        ),
      ),
    ),
  );
}

class EmptyNotice extends StatelessWidget {
  const EmptyNotice(this.message, {super.key});
  final String message;
  @override
  Widget build(BuildContext context) => Card(
    child: Padding(padding: const EdgeInsets.all(24), child: Text(message)),
  );
}

class CapabilityNotice extends StatelessWidget {
  const CapabilityNotice(this.message, {super.key});
  final String message;
  @override
  Widget build(BuildContext context) => Card(
    child: Padding(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            'CAPABILITY LIMIT',
            style: Theme.of(context).textTheme.labelSmall,
          ),
          const SizedBox(height: 8),
          Text(message),
        ],
      ),
    ),
  );
}

class RecordCard extends StatelessWidget {
  const RecordCard({
    required this.title,
    this.label,
    this.lines = const {},
    this.status,
    this.onTap,
    this.actions = const [],
    super.key,
  });
  final String title;
  final String? label;
  final Map<String, String> lines;
  final String? status;
  final VoidCallback? onTap;
  final List<Widget> actions;
  @override
  Widget build(BuildContext context) => Card(
    child: InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(4),
      child: Padding(
        padding: const EdgeInsets.all(18),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            if (label != null)
              Text(label!, style: Theme.of(context).textTheme.labelSmall),
            Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Expanded(
                  child: Text(
                    title,
                    style: Theme.of(context).textTheme.titleLarge,
                  ),
                ),
                if (onTap != null)
                  const Padding(
                    padding: EdgeInsets.only(left: 8),
                    child: Icon(Icons.arrow_forward),
                  ),
              ],
            ),
            if (status != null)
              Padding(
                padding: const EdgeInsets.only(top: 10),
                child: StatusBadge(status!),
              ),
            if (lines.isNotEmpty)
              Padding(
                padding: const EdgeInsets.only(top: 12),
                child: DataLines(lines),
              ),
            if (actions.isNotEmpty)
              Padding(
                padding: const EdgeInsets.only(top: 14),
                child: Wrap(spacing: 8, runSpacing: 8, children: actions),
              ),
          ],
        ),
      ),
    ),
  );
}

class DataLines extends StatelessWidget {
  const DataLines(this.lines, {super.key});
  final Map<String, String> lines;
  @override
  Widget build(BuildContext context) => Column(
    crossAxisAlignment: CrossAxisAlignment.start,
    children: [
      for (final entry in lines.entries)
        Padding(
          padding: const EdgeInsets.only(bottom: 10),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                entry.key.toUpperCase(),
                style: Theme.of(context).textTheme.labelSmall,
              ),
              const SizedBox(height: 3),
              SelectableText(entry.value, style: monoStyle),
            ],
          ),
        ),
    ],
  );
}

class StatusBadge extends StatelessWidget {
  const StatusBadge(this.value, {super.key});
  final String value;
  @override
  Widget build(BuildContext context) => Container(
    padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
    decoration: BoxDecoration(
      color: Theme.of(context).colorScheme.secondaryContainer,
      borderRadius: BorderRadius.circular(3),
    ),
    child: Text(
      value.replaceAll('_', ' ').toUpperCase(),
      style: monoStyle.copyWith(
        fontSize: 12,
        color: Theme.of(context).colorScheme.onSecondaryContainer,
      ),
    ),
  );
}

class SearchBox extends StatelessWidget {
  const SearchBox({required this.label, required this.onSearch, super.key});
  final String label;
  final ValueChanged<String> onSearch;
  @override
  Widget build(BuildContext context) => TextFormField(
    decoration: InputDecoration(
      labelText: label,
      prefixIcon: const Icon(Icons.search),
    ),
    maxLength: 100,
    textInputAction: TextInputAction.search,
    onFieldSubmitted: (value) => onSearch(value.trim()),
  );
}

class AdminPageControls extends StatelessWidget {
  const AdminPageControls({
    required this.page,
    required this.hasNext,
    required this.onPage,
    this.total,
    super.key,
  });
  final int page;
  final int? total;
  final bool hasNext;
  final ValueChanged<int> onPage;
  @override
  Widget build(BuildContext context) => Wrap(
    spacing: 12,
    runSpacing: 8,
    crossAxisAlignment: WrapCrossAlignment.center,
    children: [
      OutlinedButton(
        onPressed: page > 1 ? () => onPage(page - 1) : null,
        child: const Text('Previous'),
      ),
      Text(
        'Page $page${total == null ? '' : ' / $total records'}',
        style: monoStyle,
      ),
      OutlinedButton(
        onPressed: hasNext ? () => onPage(page + 1) : null,
        child: const Text('Next'),
      ),
    ],
  );
}

class FieldChoice {
  const FieldChoice(this.id, this.label, [this.subtitle]);
  final String id;
  final String label;
  final String? subtitle;
}

class AccountBoundary extends ConsumerWidget {
  const AccountBoundary({required this.scope, required this.child, super.key});
  final SessionKey scope;
  final Widget child;
  @override
  Widget build(BuildContext context, WidgetRef ref) =>
      identical(ref.watch(authProvider).key, scope)
      ? child
      : const EmptyNotice('This account session ended. Close this view.');
}

Future<T?> showAccountSheet<T>(
  BuildContext context, {
  required WidgetBuilder builder,
}) {
  final scope = ProviderScope.containerOf(
    context,
    listen: false,
  ).read(authProvider).key;
  if (scope == null) return Future.value(null);
  return showModalBottomSheet<T>(
    context: context,
    isScrollControlled: true,
    useSafeArea: true,
    builder: (context) =>
        AccountBoundary(scope: scope, child: builder(context)),
  );
}

Future<FieldChoice?> pickRecord<T>(
  BuildContext context, {
  required String title,
  required SessionQuery<Paginated<T>, ({int page, String q})> query,
  required FieldChoice Function(T) choice,
  bool searchable = true,
}) {
  final scope = ProviderScope.containerOf(
    context,
    listen: false,
  ).read(authProvider).key;
  if (scope == null) return Future.value(null);
  return showModalBottomSheet<FieldChoice>(
    context: context,
    isScrollControlled: true,
    useSafeArea: true,
    builder: (_) => AccountBoundary(
      scope: scope,
      child: LookupSheet<T>(
        title: title,
        query: query,
        choice: choice,
        searchable: searchable,
      ),
    ),
  );
}

class LookupSheet<T> extends ConsumerStatefulWidget {
  const LookupSheet({
    required this.title,
    required this.query,
    required this.choice,
    required this.searchable,
    super.key,
  });
  final String title;
  final SessionQuery<Paginated<T>, ({int page, String q})> query;
  final FieldChoice Function(T) choice;
  final bool searchable;
  @override
  ConsumerState<LookupSheet<T>> createState() => _LookupSheetState<T>();
}

class _LookupSheetState<T> extends ConsumerState<LookupSheet<T>> {
  int page = 1;
  String q = '';
  @override
  Widget build(BuildContext context) => SizedBox(
    height: MediaQuery.sizeOf(context).height * .88,
    child: TaskPage(
      eyebrow: 'Select a server record',
      title: widget.title,
      actions: [
        OutlinedButton(
          onPressed: () => Navigator.pop(context),
          child: const Text('Close'),
        ),
      ],
      children: [
        if (widget.searchable)
          SearchBox(
            label: 'Search ${widget.title}',
            onSearch: (value) => setState(() {
              q = value;
              page = 1;
            }),
          ),
        QueryPanel(
          query: widget.query,
          argument: (page: page, q: q),
          builder: (result) => Column(
            children: [
              if (result.items.isEmpty)
                const EmptyNotice('No matching records on this page.'),
              for (final item in result.items)
                Padding(
                  padding: const EdgeInsets.only(bottom: 12),
                  child: Builder(
                    builder: (context) {
                      final choice = widget.choice(item);
                      return RecordCard(
                        title: choice.label,
                        lines: {
                          if (choice.subtitle != null)
                            'Details': choice.subtitle!,
                        },
                        onTap: () => Navigator.pop(context, choice),
                      );
                    },
                  ),
                ),
              AdminPageControls(
                page: result.page,
                total: result.total,
                hasNext: result.hasNext,
                onPage: (value) => setState(() => page = value),
              ),
            ],
          ),
        ),
      ],
    ),
  );
}

Widget recordLink(BuildContext context, String path, String label) =>
    OutlinedButton.icon(
      onPressed: () => context.go(path),
      icon: const Icon(Icons.arrow_forward),
      label: Text(label),
    );
