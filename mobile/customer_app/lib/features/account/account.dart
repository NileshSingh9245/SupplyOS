import 'package:supplyos_core/supplyos_core.dart';

import '../../core/customer_contract.dart';

class CustomerProfile {
  const CustomerProfile._({
    required this.id,
    required this.code,
    required this.name,
    required this.customerType,
    required this.isActive,
    required this.creditLimit,
    required this.outstanding,
    required this.creditHeld,
    required this.cashFundedPending,
    required this.creditExposure,
    required this.availableCredit,
    required this.advanceBalance,
    this.businessName,
    this.email,
    this.phone,
    this.address,
    this.city,
    this.state,
    this.pincode,
    this.gstin,
    this.priceTier,
  });

  final String id;
  final String code;
  final String name;
  final String customerType;
  final bool isActive;
  final ServerDecimal creditLimit;
  final ServerDecimal outstanding;
  final ServerDecimal creditHeld;
  final ServerDecimal cashFundedPending;
  final ServerDecimal creditExposure;
  final ServerDecimal availableCredit;
  final ServerDecimal advanceBalance;
  final String? businessName;
  final String? email;
  final String? phone;
  final String? address;
  final String? city;
  final String? state;
  final String? pincode;
  final String? gstin;
  final String? priceTier;

  factory CustomerProfile.fromJson(Object? input) {
    final json = JsonObject(input);
    return CustomerProfile._(
      id: json.uuid('id'),
      code: serverText(json.value('code'), maxLength: 30),
      name: serverText(json.value('name'), maxLength: 200),
      customerType: json.string('customer_type'),
      isActive: json.boolean('is_active'),
      creditLimit: serverAmount(json.value('credit_limit')),
      outstanding: serverAmount(json.value('outstanding')),
      creditHeld: serverAmount(json.value('credit_held')),
      cashFundedPending: serverAmount(json.value('cash_funded_pending')),
      creditExposure: serverAmount(json.value('credit_exposure')),
      availableCredit:
          serverAmount(json.value('available_credit'), signed: true),
      advanceBalance: serverAmount(json.value('advance_balance')),
      businessName: json.optionalString('business_name'),
      email: json.optionalString('email'),
      phone: json.optionalString('phone'),
      address: json.optionalString('address'),
      city: json.optionalString('city'),
      state: json.optionalString('state'),
      pincode: json.optionalString('pincode'),
      gstin: json.optionalString('gstin'),
      priceTier: json.optionalString('price_tier'),
    );
  }

  static CustomerProfile parseOwn(Object? input) {
    final page =
        Paginated<CustomerProfile>.fromJson(input, CustomerProfile.fromJson);
    page.requirePage(1, 50);
    if (page.total == 0 && page.items.isEmpty) {
      throw const AppFailure(FailureKind.notFound);
    }
    if (page.total != 1 || page.items.length != 1) throw invalidResponse;
    return page.items.single;
  }
}

class LedgerEntry {
  const LedgerEntry._({
    required this.id,
    required this.debit,
    required this.credit,
    required this.balanceAfter,
    required this.createdAt,
    this.referenceType,
    this.referenceId,
    this.note,
  });

  final String id;
  final ServerDecimal debit;
  final ServerDecimal credit;
  final ServerDecimal balanceAfter;
  final ServerTimestamp createdAt;
  final String? referenceType;
  final String? referenceId;
  final String? note;

  factory LedgerEntry.fromJson(Object? input) {
    final json = JsonObject(input);
    return LedgerEntry._(
      id: json.uuid('id'),
      debit: serverAmount(json.value('debit')),
      credit: serverAmount(json.value('credit')),
      balanceAfter: serverAmount(json.value('balance_after'), signed: true),
      createdAt: json.timestamp('created_at'),
      referenceType: json.optionalString('reference_type'),
      referenceId: json.optionalUuid('reference_id'),
      note: json.optionalString('note'),
    );
  }
}

class PaymentReceipt {
  const PaymentReceipt._({
    required this.id,
    required this.customerId,
    required this.amount,
    required this.mode,
    required this.allocationKind,
    required this.createdAt,
    this.orderId,
    this.reference,
    this.note,
  });

  final String id;
  final String customerId;
  final String? orderId;
  final ServerDecimal amount;
  final String mode;
  final String allocationKind;
  final ServerTimestamp createdAt;
  final String? reference;
  final String? note;

  factory PaymentReceipt.fromJson(Object? input) {
    final json = JsonObject(input);
    return PaymentReceipt._(
      id: json.uuid('id'),
      customerId: json.uuid('customer_id'),
      orderId: json.optionalUuid('order_id'),
      amount: serverAmount(json.value('amount')),
      mode: json.string('mode'),
      allocationKind: json.string('allocation_kind'),
      createdAt: json.timestamp('created_at'),
      reference: json.optionalString('reference'),
      note: json.optionalString('note'),
    );
  }
}

class LedgerView {
  const LedgerView(this.profile, this.entries);
  final CustomerProfile profile;
  final List<LedgerEntry> entries;
}

class PaymentsView {
  const PaymentsView(this.profile, this.receipts);
  final CustomerProfile profile;
  final List<PaymentReceipt> receipts;
}
