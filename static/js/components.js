Vue.component(VueQrcode.name, VueQrcode)

Vue.component('satspay-paid', {
props: ['charge', 'timer'],
template: `
    <div>
        <q-icon name="check" style="color: green; font-size: 21.4em" class="fit"></q-icon>
        <div class="row text-center q-mt-lg">
        <div class="col text-center">
            <q-btn outline v-if="charge.completelink" :loading="charge.paid" :percentage="timer" type="a"
            :href="charge.completelink" :label="charge.completelinktext">{%raw%}<template v-slot:loading>
                {{charge.completelinktext}}
            </template>{%endraw%}</q-btn>
            <p v-if="harge.completelink" class="q-pt-md">Redirecting after 5 seconds</p>
        </div>
        </div>
    </div>
    `
})

Vue.component('satspay-show-qr', {
props: ['charge', 'tab', 'value', 'href'],
template: `
    <div>
    <div class="row items-center q-mb-sm">
        <div class="col text-center">
        <span v-if="tab == 'btc'" class="text-subtitle2">Send
            <span v-text="charge.amount"></span>
            sats to this onchain address</span>
            <span v-if="tab == 'ln'" class="text-subtitle2">Pay this lightning-network invoice:</span>
            <span v-if="tab == 'uqr'" class="text-subtitle2">Scan QR with a wallet supporting BIP21:</span>
        </div>
    </div>

    <a class="text-secondary" :href="href">
        <q-responsive :ratio="1" class="q-mx-md">
        <qrcode :value="value" :options="{width: 800}" class="rounded-borders"></qrcode>
        </q-responsive>
    </a>
    <div class="row items-center q-mt-lg">
        <div class="col text-center">
        <q-btn outline color="grey" @click="copyText(value)">Copy address</q-btn>
        </div>
    </div>
    </div>
    `
})