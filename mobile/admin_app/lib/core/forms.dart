import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:supplyos_core/supplyos_core.dart';

import 'contracts.dart';
import 'intents.dart';
import 'providers.dart';
import 'widgets.dart';

enum FieldKind {
  text,
  multiline,
  decimal,
  integer,
  boolean,
  choice,
  lookup,
  date,
}

class AdminField {
  const AdminField(
    this.keyName,
    this.label, {
    this.kind = FieldKind.text,
    this.initial = '',
    this.required = false,
    this.maxLength = 200,
    this.places = 2,
    this.signed = false,
    this.choices = const {},
    this.pick,
    this.help,
    this.resets = const [],
  });
  final String keyName;
  final String label;
  final FieldKind kind;
  final Object? initial;
  final bool required;
  final int maxLength;
  final int places;
  final bool signed;
  final Map<String, String> choices;
  final Future<FieldChoice?> Function(BuildContext, WidgetRef)? pick;
  final String? help;
  final List<String> resets;
}

class FormValues {
  const FormValues(this.values);
  final Map<String, Object?> values;
  String text(String key) => (values[key] ?? '').toString();
  bool boolean(String key) => values[key] == true;
  int integer(String key) => int.parse(text(key));
  Object? value(String key) => values[key];
}

class FormContext {
  const FormContext({
    required this.values,
    required this.locked,
    required this.set,
  });
  final FormValues values;
  final bool locked;
  final void Function(String, Object?) set;
}

class IntentForm<Q extends AdminInput, T> extends ConsumerStatefulWidget {
  const IntentForm({
    required this.command,
    required this.fields,
    required this.input,
    this.extra,
    this.seed = const {},
    this.fromBody,
    this.onSaved,
    this.savedMessage,
    super.key,
  });
  final AdminCommand<Q, T> command;
  final List<AdminField> fields;
  final Q Function(FormValues) input;
  final Widget Function(BuildContext, WidgetRef, FormContext)? extra;
  final Map<String, Object?> seed;
  final Map<String, Object?> Function(Map<String, Object?>)? fromBody;
  final void Function(T)? onSaved;
  final String Function(T)? savedMessage;
  @override
  ConsumerState<IntentForm<Q, T>> createState() => _IntentFormState<Q, T>();
}

class _IntentFormState<Q extends AdminInput, T>
    extends ConsumerState<IntentForm<Q, T>> {
  final _form = GlobalKey<FormState>();
  late final SessionMutation<Q, T> _owner;
  late final void Function() _remove;
  late final Map<String, Object?> _values;
  final _labels = <String, String>{};
  final _controllers = <String, TextEditingController>{};
  String? _localError;
  String? _notice;
  @override
  void initState() {
    super.initState();
    _owner = ref.read(adminIntentsProvider).owner(widget.command);
    final original = _owner.snapshot.request?.body;
    final phase = _owner.snapshot.phase;
    final frozen =
        original != null &&
            (phase == MutationPhase.uncertain ||
                phase == MutationPhase.sending ||
                phase == MutationPhase.reconciling)
        ? (widget.fromBody?.call(original) ?? original)
        : const <String, Object?>{};
    _values = {
      for (final field in widget.fields) field.keyName: field.initial,
      ...widget.seed,
      ...frozen,
    };
    for (final field in widget.fields) {
      if (field.kind != FieldKind.boolean &&
          field.kind != FieldKind.choice &&
          field.kind != FieldKind.lookup) {
        _controllers[field.keyName] = TextEditingController(
          text: (_values[field.keyName] ?? '').toString(),
        );
      }
    }
    _remove = _owner.addListener((_) {
      if (mounted) setState(() {});
    }, fireImmediately: false);
  }

  @override
  void dispose() {
    _remove();
    for (final controller in _controllers.values) {
      controller.dispose();
    }
    super.dispose();
  }

  Future<void> _submit({bool retry = false}) async {
    if (!_owner.mounted) return;
    if (!retry && !(_form.currentState?.validate() ?? false)) {
      setState(
        () => _localError = 'Check the highlighted fields before saving.',
      );
      return;
    }
    setState(() {
      _localError = null;
      _notice = null;
    });
    try {
      final response = retry
          ? await ref.read(adminIntentsProvider).retry(widget.command)
          : await ref
                .read(adminIntentsProvider)
                .submit(widget.command, widget.input(FormValues(_values)));
      if (!mounted || !_owner.mounted) return;
      setState(
        () => _notice =
            widget.savedMessage?.call(response.value) ??
            'Confirmed by the server.',
      );
      widget.onSaved?.call(response.value);
    } catch (error) {
      if (mounted && _owner.mounted) {
        setState(() => _localError = AppFailure.safe(error).message);
      }
    }
  }

  void _set(String key, Object? value) {
    if (!_owner.mounted ||
        _owner.snapshot.isBusy ||
        _owner.snapshot.phase == MutationPhase.uncertain) {
      return;
    }
    setState(() {
      if (_values[key] != value) {
        final field = widget.fields
            .where((field) => field.keyName == key)
            .firstOrNull;
        for (final reset in field?.resets ?? const <String>[]) {
          _values[reset] = '';
          _labels.remove(reset);
        }
      }
      _values[key] = value;
      _localError = null;
      _notice = null;
      final controller = _controllers[key];
      final text = value?.toString() ?? '';
      if (controller != null && controller.text != text) {
        controller.value = TextEditingValue(
          text: text,
          selection: TextSelection.collapsed(offset: text.length),
        );
      }
    });
  }

  String? _validate(AdminField field, String? value) {
    final text = (value ?? '').trim();
    if (field.required && text.isEmpty) return '${field.label} is required.';
    if (text.isEmpty) return null;
    if (text.length > field.maxLength) {
      return 'Use at most ${field.maxLength} characters.';
    }
    if (field.kind == FieldKind.lookup && !isUuid(text)) {
      return 'Choose a current server record.';
    }
    if (field.kind == FieldKind.integer &&
        !RegExp(r'^[0-9]{1,9}$').hasMatch(text)) {
      return 'Use a whole number.';
    }
    if (field.kind == FieldKind.date) {
      final date = DateTime.tryParse(text);
      if (!RegExp(r'^\d{4}-\d{2}-\d{2}$').hasMatch(text) ||
          date == null ||
          '${date.year.toString().padLeft(4, '0')}-${date.month.toString().padLeft(2, '0')}-${date.day.toString().padLeft(2, '0')}' !=
              text) {
        return 'Use a valid YYYY-MM-DD date.';
      }
    }
    if (field.kind == FieldKind.decimal) {
      try {
        decimalInput(text, places: field.places, signed: field.signed);
      } on AppFailure {
        return 'Use plain decimal text with at most ${field.places} decimal places.';
      }
    }
    return null;
  }

  Widget _field(AdminField field, bool locked) {
    final value = _values[field.keyName];
    if (field.kind == FieldKind.boolean) {
      return SwitchListTile(
        title: Text(field.label),
        subtitle: field.help == null ? null : Text(field.help!),
        value: value == true,
        onChanged: locked ? null : (value) => _set(field.keyName, value),
      );
    }
    if (field.kind == FieldKind.lookup) {
      return FormField<String>(
        initialValue: value?.toString() ?? '',
        validator: (_) => _validate(field, _values[field.keyName]?.toString()),
        builder: (state) => Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(field.label, style: Theme.of(context).textTheme.labelLarge),
            const SizedBox(height: 6),
            OutlinedButton.icon(
              onPressed: locked
                  ? null
                  : () async {
                      final picked = await field.pick?.call(context, ref);
                      if (picked == null || !mounted || !_owner.mounted) return;
                      _set(field.keyName, picked.id);
                      _labels[field.keyName] = picked.label;
                      state.didChange(picked.id);
                    },
              icon: const Icon(Icons.search),
              label: Text(
                _labels[field.keyName] ??
                    (value == null || value == ''
                        ? 'Choose ${field.label}'
                        : 'Selected: $value'),
              ),
            ),
            if (!field.required && value != null && value != '')
              TextButton(
                onPressed: locked
                    ? null
                    : () {
                        _set(field.keyName, '');
                        state.didChange('');
                      },
                child: const Text('Clear selection'),
              ),
            if (state.errorText != null)
              Text(
                state.errorText!,
                style: TextStyle(color: Theme.of(context).colorScheme.error),
              ),
            if (field.help != null) Text(field.help!),
          ],
        ),
      );
    }
    if (field.kind == FieldKind.choice) {
      final text = value?.toString() ?? '';
      final choices = {
        ...field.choices,
        if (!field.choices.containsKey(text)) text: 'Original selection: $text',
      };
      return DropdownButtonFormField<String>(
        key: ValueKey('${field.keyName}:$text'),
        initialValue: text,
        isExpanded: true,
        itemHeight: null,
        decoration: InputDecoration(
          labelText: field.label,
          helperText: field.help,
        ),
        items: [
          for (final entry in choices.entries)
            DropdownMenuItem(
              value: entry.key,
              child: Text(entry.value, maxLines: 2),
            ),
        ],
        onChanged: locked ? null : (value) => _set(field.keyName, value),
        validator: (value) => _validate(field, value),
      );
    }
    return TextFormField(
      key: ValueKey(field.keyName),
      controller: _controllers[field.keyName],
      enabled: !locked,
      decoration: InputDecoration(
        labelText: field.label,
        helperText: field.help,
      ),
      maxLength: field.maxLength,
      maxLines: field.kind == FieldKind.multiline ? 3 : 1,
      textInputAction: field.kind == FieldKind.multiline
          ? TextInputAction.newline
          : TextInputAction.next,
      keyboardType: field.kind == FieldKind.multiline
          ? TextInputType.multiline
          : field.kind == FieldKind.decimal
          ? TextInputType.numberWithOptions(decimal: true, signed: field.signed)
          : field.kind == FieldKind.integer
          ? TextInputType.number
          : TextInputType.text,
      onChanged: (value) => _set(field.keyName, value),
      validator: (value) => _validate(field, value),
    );
  }

  @override
  Widget build(BuildContext context) {
    if (!_owner.mounted) {
      return const EmptyNotice('This account session ended.');
    }
    ref.watch(adminIntentsProvider);
    final state = _owner.snapshot;
    final uncertain = state.phase == MutationPhase.uncertain;
    final locked = state.isBusy || uncertain;
    return Form(
      key: _form,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          for (final field in widget.fields)
            Padding(
              padding: const EdgeInsets.only(bottom: 16),
              child: _field(field, locked),
            ),
          if (widget.extra != null)
            widget.extra!(
              context,
              ref,
              FormContext(
                values: FormValues(_values),
                locked: locked,
                set: _set,
              ),
            ),
          if (_localError != null || state.failure != null)
            Semantics(
              liveRegion: true,
              child: Padding(
                padding: const EdgeInsets.symmetric(vertical: 12),
                child: Text(
                  _localError ?? state.failure!.message,
                  style: TextStyle(color: Theme.of(context).colorScheme.error),
                ),
              ),
            ),
          if (_notice != null)
            Semantics(
              liveRegion: true,
              child: Padding(
                padding: const EdgeInsets.symmetric(vertical: 12),
                child: Text(_notice!),
              ),
            ),
          if (uncertain)
            const CapabilityNotice(
              'Result unconfirmed. The original fields, account and request key are locked. Closing this form does not unlock it. Refreshing lists is not proof that it failed.',
            ),
          if (uncertain && !state.canRetry)
            const CapabilityNotice(
              'This endpoint has no replay contract. Authoritative server reconciliation is required before another request; no automatic or new-key retry is available.',
            ),
          if (state.isBusy)
            Semantics(
              liveRegion: true,
              child: const Text('Waiting for a confirmed server outcome...'),
            ),
          const SizedBox(height: 12),
          FilledButton.icon(
            onPressed: locked ? null : () => _submit(),
            icon: const Icon(Icons.check),
            label: Text(widget.command.title),
          ),
          if (state.canRetry)
            Padding(
              padding: const EdgeInsets.only(top: 12),
              child: OutlinedButton.icon(
                onPressed: () => _submit(retry: true),
                icon: const Icon(Icons.replay),
                label: const Text('Retry unchanged original request'),
              ),
            ),
        ],
      ),
    );
  }
}
