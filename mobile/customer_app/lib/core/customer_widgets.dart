import 'package:flutter/material.dart';
import 'package:supplyos_core/supplyos_core.dart';

class CustomerSection extends StatelessWidget {
  const CustomerSection(
      {required this.title, required this.child, this.icon, super.key});

  final String title;
  final Widget child;
  final IconData? icon;

  @override
  Widget build(BuildContext context) => Container(
        margin: const EdgeInsets.only(bottom: 16),
        padding: const EdgeInsets.all(20),
        decoration: BoxDecoration(
          color: Theme.of(context).colorScheme.surface,
          border: Border.all(color: const Color(0xFFE4E4E7)),
          borderRadius: BorderRadius.circular(4),
        ),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          if (icon != null) ...[
            Container(
              padding: const EdgeInsets.all(8),
              color: Theme.of(context).colorScheme.secondary,
              child: Icon(icon, size: 22),
            ),
            const SizedBox(height: 12),
          ],
          Text(title, style: Theme.of(context).textTheme.titleLarge),
          const SizedBox(height: 16),
          child,
        ]),
      );
}

class DataField extends StatelessWidget {
  const DataField(this.label, this.value, {super.key});
  final String label;
  final String value;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.only(bottom: 12),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(label, style: Theme.of(context).textTheme.labelMedium),
          const SizedBox(height: 3),
          SelectableText(value, style: Theme.of(context).textTheme.bodyLarge),
        ]),
      );
}

class CustomerNotice extends StatelessWidget {
  const CustomerNotice(this.message, {this.isError = false, super.key});
  final String message;
  final bool isError;

  @override
  Widget build(BuildContext context) => Semantics(
        liveRegion: true,
        child: Container(
          width: double.infinity,
          padding: const EdgeInsets.all(16),
          margin: const EdgeInsets.only(bottom: 16),
          decoration: BoxDecoration(
            color: isError ? const Color(0xFFFFF1F0) : const Color(0xFFF0F4DD),
            border: Border(
                left: BorderSide(
              width: 4,
              color: isError
                  ? Theme.of(context).colorScheme.error
                  : const Color(0xFF556300),
            )),
          ),
          child: Text(message),
        ),
      );
}

class InlineReadState extends StatelessWidget {
  const InlineReadState(
      {required this.title, this.error, this.onRetry, super.key});
  final String title;
  final Object? error;
  final VoidCallback? onRetry;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 24),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(title, style: Theme.of(context).textTheme.titleMedium),
          if (error != null) ...[
            const SizedBox(height: 8),
            Semantics(
                liveRegion: true, child: Text(AppFailure.safe(error!).message)),
          ],
          if (onRetry != null) ...[
            const SizedBox(height: 12),
            OutlinedButton(onPressed: onRetry, child: const Text('Retry')),
          ],
        ]),
      );
}

class CustomerList extends StatelessWidget {
  const CustomerList({required this.children, super.key});
  final List<Widget> children;

  @override
  Widget build(BuildContext context) => Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 1000),
          child: ListView(
            physics: const AlwaysScrollableScrollPhysics(),
            padding: const EdgeInsets.all(20),
            children: children,
          ),
        ),
      );
}

class CustomerSearch extends StatefulWidget {
  const CustomerSearch(
      {required this.label,
      required this.initialText,
      required this.onSearch,
      super.key});
  final String label;
  final String initialText;
  final ValueChanged<String> onSearch;

  @override
  State<CustomerSearch> createState() => _CustomerSearchState();
}

class _CustomerSearchState extends State<CustomerSearch> {
  late final _controller = TextEditingController(text: widget.initialText);

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => TextField(
        controller: _controller,
        maxLength: 200,
        textInputAction: TextInputAction.search,
        onSubmitted: (value) => widget.onSearch(value.trim()),
        decoration: InputDecoration(
          labelText: widget.label,
          counterText: '',
          prefixIcon: const Icon(Icons.search),
          suffixIcon: IconButton(
            tooltip: 'Search',
            onPressed: () => widget.onSearch(_controller.text.trim()),
            icon: const Icon(Icons.arrow_forward),
          ),
        ),
      );
}

void showCustomerFailure(BuildContext context, Object error) {
  final safe = AppFailure.safe(error);
  if (safe.kind == FailureKind.superseded) return;
  ScaffoldMessenger.of(context)
      .showSnackBar(SnackBar(content: Text(safe.message)));
}
